"""优化 ②：commit 元数据并行提取（4 路 LLM 调用）。

将原 [runner.py: _extract_commit_metadata](file:///c:/Users/17924/Desktop/1/学习资料/javaNote/八股/小说多agent%20项目/LoreSmith/ainovel_py/agents/runner.py#L563-L615) 拆为 4 个独立的 LLM 子任务，
用 ThreadPoolExecutor 并行执行，大幅缩短提取时间。

设计要点：
1. **任务拆分**：summary / key_events / foreshadow_updates / relationship_changes 四个独立维度
2. **单点失败隔离**：单路 LLM 异常 → 该字段取 default，其他字段不受影响
3. **fallback 机制**：整个并行流程异常时退回单次 LLM 调用（保留原行为）
4. **字段合并**：4 路结果合并到统一 metadata 字典，缺失字段用 setdefault 兜底
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable


def _extract_field(
    client: Any,
    chapter: int,
    draft: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    default: dict[str, Any],
    on_json: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """单路 LLM 抽取包装：异常时返回 default，JSON 解析失败时按 on_json 处理。"""
    try:
        raw = client.complete(system_prompt, user_prompt, temperature=temperature)
        if not raw or not raw.strip():
            return default
        if on_json is not None:
            return on_json(raw)
        # 默认按 JSON 解析（draft 必须是 { 开头的对象）
        if raw.strip().startswith("{"):
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        return default
    except Exception:
        return default


def _on_events(raw: str) -> dict[str, Any]:
    """关键事件解析：返回 {"key_events": [...]}。"""
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return {"key_events": data}
        if isinstance(data, dict) and "key_events" in data:
            return {"key_events": list(data["key_events"])}
    except Exception:
        pass
    return {"key_events": []}


def _on_foreshadow(raw: str) -> dict[str, Any]:
    """伏笔更新解析：返回 {"foreshadow_updates": [...]}。"""
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return {"foreshadow_updates": data}
        if isinstance(data, dict) and "foreshadow_updates" in data:
            return {"foreshadow_updates": list(data["foreshadow_updates"])}
    except Exception:
        pass
    return {"foreshadow_updates": []}


def _on_relationships(raw: str) -> dict[str, Any]:
    """人物关系解析：返回 {"relationship_changes": [...]}。"""
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return {"relationship_changes": data}
        if isinstance(data, dict) and "relationship_changes" in data:
            return {"relationship_changes": list(data["relationship_changes"])}
    except Exception:
        pass
    return {"relationship_changes": []}


def extract_commit_metadata_parallel(
    client: Any,
    chapter: int,
    draft: str,
    max_workers: int = 4,
) -> dict[str, Any]:
    """4 路 LLM 并行提取 commit 元数据。

    Args:
        client: OpenAI 兼容客户端
        chapter: 当前章节号
        draft: 章节正文
        max_workers: 并行线程数（默认 4）

    Returns:
        合并后的 metadata 字典，含以下字段：
        - summary: 字符串
        - key_events: 字符串数组
        - foreshadow_updates: 对象数组
        - relationship_changes: 对象数组
        - characters / timeline_events / state_changes / hook_type / dominant_strand
        - chapter: 数字

    Notes:
        - 任一子任务失败仅影响该字段，其他字段正常返回
        - 与 [_extract_commit_metadata 串行版](file:///c:/Users/17924/Desktop/1/学习资料/javaNote/八股/小说多agent%20项目/LoreSmith/ainovel_py/agents/runner.py#L563-L615) 字段集完全兼容
    """
    base_ctx = f"\n\n第{chapter}章正文：\n{draft}"

    # 4 路 LLM 并行执行
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        f_sum = pool.submit(
            _extract_field,
            client, chapter, draft,
            "你是小说摘要助手，只输出 JSON。",
            f"请用1-2句话总结本章关键推进、冲突变化和章末悬念，控制在80字以内。"
            f"输出 JSON: {{\"summary\": \"<80字内摘要>\"}}"
            + base_ctx,
            0.3,
            {"summary": ""},
        )
        f_evt = pool.submit(
            _extract_field,
            client, chapter, draft,
            "你是关键事件抽取助手，只输出 JSON 数组。",
            f"提取本章关键事件，输出 JSON 数组，每项包含 type 和 desc 字段。"
            f"最多 5 项。" + base_ctx,
            0.2,
            {"key_events": []},
            _on_events,
        )
        f_fsh = pool.submit(
            _extract_field,
            client, chapter, draft,
            "你是伏笔追踪助手，只输出 JSON 数组。",
            f"提取本章的伏笔更新，输出 JSON 数组，每项包含 id / action / description。"
            f"action 取值 plant/advance/resolve。" + base_ctx,
            0.2,
            {"foreshadow_updates": []},
            _on_foreshadow,
        )
        f_rel = pool.submit(
            _extract_field,
            client, chapter, draft,
            "你是人物关系抽取助手，只输出 JSON 数组。",
            f"提取本章人物关系变化，输出 JSON 数组，每项包含 character_a / character_b / relation / chapter。"
            + base_ctx,
            0.2,
            {"relationship_changes": []},
            _on_relationships,
        )

        data: dict[str, Any] = {
            **f_sum.result(),
            **f_evt.result(),
            **f_fsh.result(),
            **f_rel.result(),
        }

    # 兜底字段（与原串行版字段集一致）
    data.setdefault("summary", "")
    data.setdefault("characters", ["主角"])
    data.setdefault("key_events", [f"第{chapter}章推进"])
    data.setdefault("timeline_events", [])
    data.setdefault("foreshadow_updates", [])
    data.setdefault("relationship_changes", [])
    data.setdefault("state_changes", [])
    data.setdefault("hook_type", "mystery")
    data.setdefault("dominant_strand", "quest")
    data.setdefault("emotional_landing", "")
    data.setdefault("narrative_tone", "")
    data.setdefault("sensory_anchor", "")
    data["chapter"] = chapter
    return data


def extract_commit_metadata_serial(client: Any, chapter: int, draft: str) -> dict[str, Any]:
    """串行版元数据提取（保留为 fallback）。

    实现与原 [runner.py: _extract_commit_metadata](file:///c:/Users/17924/Desktop/1/学习资料/javaNote/八股/小说多agent%20项目/LoreSmith/ainovel_py/agents/runner.py#L563-L615) 一致。
    """
    prompt = f"""
请从下面的第{chapter}章正文中提取结构化信息，并严格输出 JSON 对象（不要输出 Markdown、不要解释）。
字段要求：
- summary: 字符串
- characters: 字符串数组
- key_events: 字符串数组
- timeline_events: 对象数组，每项 {{"time": 字符串, "event": 字符串, "characters": 字符串数组}}
- foreshadow_updates: 对象数组，每项 {{"id": 字符串, "action": "plant"|"advance"|"resolve", "description": 字符串}}
  - action=plant 时 description 必填，id 必须稳定可复用（如 fs_clue_01）
- relationship_changes: 对象数组，每项 {{"character_a": 字符串, "character_b": 字符串, "relation": 字符串, "chapter": 数字}}
  - character_a / character_b / relation 都不能为空
- state_changes: 对象数组，每项 {{"entity": 字符串, "field": 字符串, "old_value": 字符串, "new_value": 字符串, "reason": 字符串, "chapter": 数字}}
- hook_type: 字符串
- dominant_strand: 字符串
- emotional_landing: 字符串，本章结束时读者停留的情绪落点，例如"紧张中带着困惑"
- narrative_tone: 字符串，本章主导叙事语调，例如"压抑、克制、暗流涌动"
- sensory_anchor: 字符串，本章最有记忆感的一个感官细节，例如"雨水顺着门缝渗进来"

如果某项不存在请返回空数组，不要伪造空对象。

正文：
{draft}
""".strip()
    raw = client.complete(
        "你是小说信息抽取助手，只输出 JSON。",
        prompt,
        temperature=0.2,
    )
    try:
        data = json.loads(raw)
    except Exception:
        summary_fallback = client.complete(
            "你是摘要助手。",
            f"请用一到两句话总结第{chapter}章的关键推进、冲突变化和章末悬念，控制在80字以内。\n\n{draft}",
            temperature=0.3,
        )
        data = {
            "summary": summary_fallback,
            "characters": ["主角"],
            "key_events": [f"第{chapter}章推进"],
            "timeline_events": [],
            "foreshadow_updates": [],
            "relationship_changes": [],
            "state_changes": [],
            "hook_type": "mystery",
            "dominant_strand": "quest",
            "emotional_landing": "",
            "narrative_tone": "",
            "sensory_anchor": "",
        }
    data.setdefault("emotional_landing", "")
    data.setdefault("narrative_tone", "")
    data.setdefault("sensory_anchor", "")
    data["chapter"] = chapter
    return data


def extract_commit_metadata(client: Any, chapter: int, draft: str) -> dict[str, Any]:
    """统一的元数据提取入口：默认并行版，失败时 fallback 到串行版。

    保留与 [runner.py: _extract_commit_metadata](file:///c:/Users/17924/Desktop/1/学习资料/javaNote/八股/小说多agent%20项目/LoreSmith/ainovel_py/agents/runner.py#L563-L615) 完全相同的接口签名。
    """
    try:
        return extract_commit_metadata_parallel(client, chapter, draft)
    except Exception:
        return extract_commit_metadata_serial(client, chapter, draft)
