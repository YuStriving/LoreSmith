"""EditorAgent 单测。

覆盖 4 类场景：
1. execute() 完整链路：mock client + runner.call_tool
2. _extract_commit_metadata：成功 / JSON 解析失败 / 二次 LLM 失败
3. _generate_review_payload：成功 / JSON 失败 / setdefault chapter
4. run_write_commit_cycle：metadata 字段兜底
"""
from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock

import pytest

from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.agents.roles.editor import (
    EditorAgent,
    _FALLBACK_DIMENSION_SCORES,
    _call_with_retry,
)


# ---------- 共用 fixture ----------

@pytest.fixture
def agent() -> EditorAgent:
    """构造 EditorAgent，cfg/runner/store/assets/emit_event 全部 mock。"""
    cfg = MagicMock()
    cfg.providers = {"openai": MagicMock(api_key="test-key", base_url="http://localhost")}
    runner = MagicMock()
    store = MagicMock()
    assets = MagicMock()
    assets.prompts.get.return_value = "mock prompt"
    assets.prompts.get.side_effect = lambda k, default=None: {
        "editor": "mock editor prompt"
    }.get(k, default or "")
    assets.references = MagicMock()
    emit_event = MagicMock()
    return EditorAgent(
        cfg=cfg,
        runner=runner,
        store=store,
        assets=assets,
        emit_event=emit_event,
        emit_stream=MagicMock(),
    )


# ---------- 1. _call_with_retry 行为 ----------

def test_call_with_retry_success_first_attempt():
    client = MagicMock(spec=OpenAICompatClient)
    client.complete.return_value = "ok"
    result = _call_with_retry(client, "sys", "user", 0.5)
    assert result == "ok"
    assert client.complete.call_count == 1


def test_call_with_retry_success_on_second_attempt():
    client = MagicMock(spec=OpenAICompatClient)
    client.complete.side_effect = [
        urllib.error.URLError("timeout"),
        "ok",
    ]
    result = _call_with_retry(client, "sys", "user", 0.5, max_attempts=2)
    assert result == "ok"
    assert client.complete.call_count == 2


def test_call_with_retry_raises_after_max_attempts():
    client = MagicMock(spec=OpenAICompatClient)
    client.complete.side_effect = urllib.error.URLError("persistent timeout")
    with pytest.raises(urllib.error.URLError):
        _call_with_retry(client, "sys", "user", 0.5, max_attempts=2)
    assert client.complete.call_count == 2


def test_call_with_retry_does_not_catch_json_error():
    client = MagicMock(spec=OpenAICompatClient)
    # JSON 解析错误不应被 retry helper 吞掉（不是网络错误）
    client.complete.side_effect = ValueError("json decode failed")
    with pytest.raises(ValueError, match="json decode failed"):
        _call_with_retry(client, "sys", "user", 0.5, max_attempts=2)
    # 网络/超时错误才重试，ValueError 只调用 1 次
    assert client.complete.call_count == 1


# ---------- 2. _extract_commit_metadata 场景 ----------

def test_extract_metadata_success(agent: EditorAgent):
    """LLM 返回有效 JSON → is_fallback=False。"""
    client = MagicMock(spec=OpenAICompatClient)
    llm_payload = {
        "summary": "主角觉醒",
        "characters": ["主角"],
        "key_events": ["觉醒"],
        "foreshadow_updates": [{"id": "fs1", "action": "plant", "description": "x"}],
    }
    client.complete.return_value = json.dumps(llm_payload)
    # 绕过 build_client 真实构造
    agent.build_client = MagicMock(return_value=client)

    data = agent._extract_commit_metadata(client, chapter=1, draft="正文")

    assert data["is_fallback"] is False
    assert data["chapter"] == 1
    assert data["summary"] == "主角觉醒"
    assert data["key_events"] == ["觉醒"]


def test_extract_metadata_json_failure_falls_back(agent: EditorAgent):
    """LLM 返回非 JSON → 走兜底，is_fallback=True，调用方收到 WARN。"""
    client = MagicMock(spec=OpenAICompatClient)
    # 主 LLM 返回非 JSON，summary_fallback 二次 LLM 成功
    client.complete.side_effect = [
        "not json at all",
        "兜底摘要成功",
    ]

    data = agent._extract_commit_metadata(client, chapter=2, draft="正文")

    assert data["is_fallback"] is True
    assert data["chapter"] == 2
    assert data["summary"] == "兜底摘要成功"
    assert data["key_events"] == ["第2章推进"]
    # 至少 emit_event 一次 WARN
    warn_calls = [
        c for c in agent.emit_event.call_args_list
        if c.kwargs.get("level") == "warn" or (c.args and len(c.args) > 0 and getattr(c.args[0], "level", None) == "warn")
    ]
    assert len(warn_calls) >= 1


def test_extract_metadata_both_llm_fail_summary_empty(agent: EditorAgent):
    """主 LLM + 二次 LLM 都失败 → summary=""，is_fallback=True，发两条 WARN。"""
    client = MagicMock(spec=OpenAICompatClient)
    client.complete.side_effect = [
        "not json",
        urllib.error.URLError("summary 二次失败"),
    ]

    data = agent._extract_commit_metadata(client, chapter=3, draft="正文")

    assert data["is_fallback"] is True
    assert data["summary"] == ""
    # 两次 WARN
    warn_count = sum(
        1 for c in agent.emit_event.call_args_list
        if c.args and getattr(c.args[0], "level", None) == "warn"
    )
    assert warn_count >= 2


# ---------- 3. _generate_review_payload 场景 ----------

def test_generate_review_payload_success(agent: EditorAgent):
    """LLM 返回有效 JSON → is_fallback=False，setdefault 不覆盖。"""
    client = MagicMock(spec=OpenAICompatClient)
    llm_payload = {
        "chapter": 5,
        "scope": "chapter",
        "dimensions": [{"dimension": "consistency", "score": 90, "verdict": "pass"}],
        "issues": [],
        "verdict": "accept",
        "summary": "ok",
        "affected_chapters": [],
    }
    client.complete.return_value = json.dumps(llm_payload)
    agent.runner.call_tool.return_value = {"content": "draft text"}

    data = agent._generate_review_payload(client, chapter=5)

    assert data["is_fallback"] is False
    # chapter 来自 LLM，被 setdefault 保留（不覆盖）
    assert data["chapter"] == 5
    assert data["verdict"] == "accept"


def test_generate_review_payload_json_failure_falls_back(agent: EditorAgent):
    """LLM 返回非 JSON → 7 维度兜底，is_fallback=True，发 WARN。"""
    client = MagicMock(spec=OpenAICompatClient)
    client.complete.return_value = "totally broken response"
    agent.runner.call_tool.return_value = {"content": "draft text"}

    data = agent._generate_review_payload(client, chapter=7)

    assert data["is_fallback"] is True
    assert data["chapter"] == 7
    assert data["verdict"] == "polish"
    assert data["scope"] == "chapter"
    # 7 个维度全部使用 _FALLBACK_DIMENSION_SCORES
    assert len(data["dimensions"]) == len(_FALLBACK_DIMENSION_SCORES) == 7
    assert data["dimensions"][0]["dimension"] == "consistency"
    # 至少一条 WARN
    warn_calls = [
        c for c in agent.emit_event.call_args_list
        if c.args and getattr(c.args[0], "level", None) == "warn"
    ]
    assert len(warn_calls) >= 1


def test_generate_review_payload_setdefault_chapter(agent: EditorAgent):
    """LLM 成功时 chapter 来自 LLM（不被外部覆盖）。"""
    client = MagicMock(spec=OpenAICompatClient)
    llm_payload = {
        "chapter": 999,  # LLM 提供的 chapter
        "scope": "chapter",
        "dimensions": [],
        "issues": [],
        "verdict": "accept",
    }
    client.complete.return_value = json.dumps(llm_payload)
    agent.runner.call_tool.return_value = {"content": "draft"}

    # 外部传 chapter=1，但 LLM 返回 chapter=999
    data = agent._generate_review_payload(client, chapter=1)

    # setdefault 不覆盖 → 保留 LLM 的 999
    assert data["chapter"] == 999


# ---------- 4. run_write_commit_cycle 场景 ----------

def test_run_write_commit_cycle_with_full_metadata(agent: EditorAgent):
    """完整 metadata → 字段原样传给 commit_chapter。"""
    draft_res = {"ok": True}
    commit_res = {"chapter": 1, "saved": True}
    agent.runner.call_tool.side_effect = [draft_res, None, commit_res]

    metadata = {
        "characters": ["A", "B"],
        "key_events": ["evt1", "evt2"],
        "timeline_events": [{"time": "t1"}],
        "foreshadow_updates": [{"id": "fs1"}],
        "relationship_changes": [{"a": "b"}],
        "state_changes": [{"e": "f"}],
        "hook_type": "cliffhanger",
        "dominant_strand": "mystery",
    }
    d, c = agent.run_write_commit_cycle(1, "draft", "summary", metadata)

    assert d is draft_res
    assert c is commit_res
    # 检查 commit_chapter 调用的 payload
    commit_call = agent.runner.call_tool.call_args_list[2]
    assert commit_call.args[0] == "commit_chapter"
    payload = commit_call.args[1]
    assert payload["chapter"] == 1
    assert payload["characters"] == ["A", "B"]
    assert payload["hook_type"] == "cliffhanger"


def test_run_write_commit_cycle_with_missing_metadata(agent: EditorAgent):
    """metadata 字段缺失 → 全部回退到默认。"""
    agent.runner.call_tool.side_effect = [{}, None, {}]

    d, c = agent.run_write_commit_cycle(2, "draft", "sum", {})

    commit_call = agent.runner.call_tool.call_args_list[2]
    payload = commit_call.args[1]
    assert payload["characters"] == ["主角"]  # 默认
    assert payload["key_events"] == ["第2章推进"]  # 默认
    assert payload["timeline_events"] == []
    assert payload["hook_type"] == "mystery"


# ---------- 5. execute() 完整链路 ----------

def test_execute_calls_llm_review_and_save_review(agent: EditorAgent):
    """execute() 端到端：LLM 评审 → save_review。"""
    client = MagicMock(spec=OpenAICompatClient)
    client.complete.return_value = json.dumps({
        "chapter": 3,
        "scope": "chapter",
        "dimensions": [],
        "issues": [],
        "verdict": "accept",
    })
    agent.build_client = MagicMock(return_value=client)
    agent.runner.call_tool.side_effect = [
        {"context": "novel ctx"},   # novel_context
        {"content": "draft text"},  # read_chapter
        {"saved": True, "review_id": "r1"},  # save_review
    ]

    result = agent.execute(chapter=3)

    assert result["chapter"] == 3
    assert result["review"]["saved"] is True
    assert result["review_payload"]["verdict"] == "accept"
    # runner.call_tool 调用了 novel_context + read_chapter + save_review
    tool_names = [c.args[0] for c in agent.runner.call_tool.call_args_list]
    assert "novel_context" in tool_names
    assert "read_chapter" in tool_names
    assert "save_review" in tool_names
