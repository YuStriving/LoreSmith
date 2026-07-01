"""AgentRegistry 单测。

覆盖：
1. register 必填字段校验（name/role/description）
2. 重复注册抛 ValueError
3. unregister 容错
4. get 抛 KeyError / has 不抛
5. all_specs / all_names 顺序与注册顺序一致
6. allowed_targets 入口（from_agent=""）返回除 supervisor 之外的全部
7. allowed_targets 未知 from_agent 兜底返回全部
8. filter_candidates 白名单 + 排除集合
"""
from __future__ import annotations

import pytest

from ainovel_py.agents.orchestrator.registry import AgentRegistry, AgentSpec


# ---------- 辅助：构造测试用 AgentSpec ----------

def _spec(name: str = "writer", **kw) -> AgentSpec:
    defaults = dict(
        name=name,
        role="测试角色",
        description="测试描述",
        tools=[],
        allowed_next=["editor"],
        can_parallel=False,
        llm_role="writer",
        model_capability="longform",
        factory=lambda **kw: None,
    )
    defaults.update(kw)
    return AgentSpec(**defaults)


# ---------- 1. register 必填字段校验 ----------

def test_register_requires_name():
    with pytest.raises(ValueError, match="name is required"):
        AgentRegistry().register(AgentSpec(name="", role="r", description="d"))


def test_register_requires_role():
    with pytest.raises(ValueError, match="role is required"):
        AgentRegistry().register(AgentSpec(name="x", role="", description="d"))


def test_register_requires_description():
    with pytest.raises(ValueError, match="description is required"):
        AgentRegistry().register(AgentSpec(name="x", role="r", description=""))


def test_register_happy_path():
    reg = AgentRegistry()
    spec = _spec()
    reg.register(spec)
    assert reg.has("writer")
    assert reg.get("writer") is spec


# ---------- 2. 重复注册 ----------

def test_register_duplicate_raises():
    reg = AgentRegistry()
    reg.register(_spec("writer"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_spec("writer"))


# ---------- 3. unregister ----------

def test_unregister_existing():
    reg = AgentRegistry()
    reg.register(_spec("writer"))
    reg.unregister("writer")
    assert not reg.has("writer")


def test_unregister_nonexistent_no_error():
    reg = AgentRegistry()
    reg.unregister("ghost")  # 不抛异常


# ---------- 4. get / has ----------

def test_get_unknown_raises_keyerror():
    reg = AgentRegistry()
    with pytest.raises(KeyError, match="unknown agent"):
        reg.get("ghost")


def test_has_does_not_raise():
    reg = AgentRegistry()
    assert not reg.has("ghost")
    reg.register(_spec("writer"))
    assert reg.has("writer")


# ---------- 5. all_specs / all_names 顺序 ----------

def test_all_specs_preserves_insertion_order():
    reg = AgentRegistry()
    reg.register(_spec("writer"))
    reg.register(_spec("architect"))
    reg.register(_spec("editor"))
    names = [s.name for s in reg.all_specs()]
    assert names == ["writer", "architect", "editor"]
    assert reg.all_names() == ["writer", "architect", "editor"]


# ---------- 6. allowed_targets 入口 ----------

def test_allowed_targets_entry_excludes_supervisor():
    reg = AgentRegistry()
    reg.register(_spec("writer"))
    reg.register(_spec("architect"))
    reg.register(_spec("supervisor"))
    targets = reg.allowed_targets("")
    assert "supervisor" not in targets
    assert set(targets) == {"writer", "architect"}


# ---------- 7. allowed_targets 未知 from_agent 兜底 ----------

def test_allowed_targets_unknown_from_agent_returns_all():
    reg = AgentRegistry()
    reg.register(_spec("writer"))
    reg.register(_spec("architect"))
    reg.register(_spec("supervisor"))
    targets = reg.allowed_targets("ghost")
    assert "supervisor" not in targets
    assert set(targets) == {"writer", "architect"}


def test_allowed_targets_known_from_agent_uses_allowed_next():
    reg = AgentRegistry()
    reg.register(_spec("writer", allowed_next=["editor", "writer"]))
    reg.register(_spec("editor", allowed_next=["supervisor"]))
    reg.register(_spec("supervisor", allowed_next=["writer"]))
    targets = reg.allowed_targets("writer")
    assert set(targets) == {"editor", "writer"}


# ---------- 8. filter_candidates ----------

def test_filter_candidates_excludes_set():
    reg = AgentRegistry()
    reg.register(_spec("writer", allowed_next=["editor", "architect"]))
    reg.register(_spec("editor", allowed_next=["writer"]))
    reg.register(_spec("architect", allowed_next=["writer"]))
    candidates = reg.filter_candidates("writer", exclude={"architect"})
    assert "architect" not in candidates
    assert "editor" in candidates


def test_filter_candidates_no_exclude():
    reg = AgentRegistry()
    reg.register(_spec("writer", allowed_next=["editor"]))
    reg.register(_spec("editor", allowed_next=["writer"]))
    candidates = reg.filter_candidates("writer")
    assert "editor" in candidates


def test_filter_candidates_exclude_none():
    reg = AgentRegistry()
    reg.register(_spec("writer", allowed_next=["editor"]))
    candidates = reg.filter_candidates("writer", exclude=None)
    assert "editor" in candidates
