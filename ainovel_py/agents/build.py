from __future__ import annotations

from ainovel_py.agents.orchestrator.registry import AgentRegistry, AgentSpec
from ainovel_py.agents.runner import AgentRunner
from ainovel_py.agents.roles import (
    ArchitectAgent,
    EditorAgent,
    RewriteAgent,
    SupervisorAgent,
    WriterAgent,
)
from ainovel_py.assets import AssetBundle
from ainovel_py.bootstrap.config import Config
from ainovel_py.store.store import Store
from ainovel_py.tools import (
    CheckConsistencyTool,
    CommitChapterTool,
    DraftChapterTool,
    NovelContextTool,
    PlanChapterTool,
    ReadChapterTool,
    SaveArcSummaryTool,
    SaveFoundationTool,
    SaveReviewTool,
    SaveVolumeSummaryTool,
)


def build_tool_registry(store: Store) -> dict[str, object]:
    tools = [
        NovelContextTool(store, style=store.run_meta.load().style if store.run_meta.load() else "default"),
        SaveFoundationTool(store),
        ReadChapterTool(store),
        PlanChapterTool(store),
        DraftChapterTool(store),
        CheckConsistencyTool(store),
        CommitChapterTool(store),
        SaveReviewTool(store),
        SaveArcSummaryTool(store),
        SaveVolumeSummaryTool(store),
    ]
    return {tool.name(): tool for tool in tools}


def build_agent_registry(
    cfg: Config,
    store: Store,
    runner: AgentRunner,
    assets: AssetBundle,
    emit_event,
    emit_stream,
) -> AgentRegistry:
    """构建 Agent 注册表，注册 6 个核心 agent（阶段 A）。

    阶段 A 改造：
    - 把原来隐式写在 LangGraphRuntime._init_agents 中的 5 个 agent 改为显式注册
    - 新增 editor_review agent（与 editor_commit 共享 EditorAgent 实例，但作为不同 spec）
    - 所有 spec 携带 description / tools / allowed_next 元数据，为阶段 B 的 LLM 决策做准备

    扩展新 agent：只需在本函数中 register() 一个新 AgentSpec，不需要改 dispatcher。
    """
    reg = AgentRegistry()
    common = dict(
        cfg=cfg,
        runner=runner,
        store=store,
        assets=assets,
        emit_event=emit_event,
        emit_stream=emit_stream,
    )

    reg.register(AgentSpec(
        name="architect",
        role="章节规划师",
        description="根据大纲、上一章摘要、人物状态生成下一章骨架（plan_chapter）",
        tools=["plan_chapter", "novel_context"],
        allowed_next=["writer", "architect"],
        can_parallel=False,
        llm_role="architect",
        model_capability="planner",
        factory=lambda **kw: ArchitectAgent(**kw),
    ))

    reg.register(AgentSpec(
        name="writer",
        role="正文章节写手",
        description="基于 plan 生成正文（draft_chapter），流式输出",
        tools=["draft_chapter"],
        allowed_next=["editor_commit", "writer"],
        can_parallel=False,
        llm_role="writer",
        model_capability="longform",
        factory=lambda **kw: WriterAgent(**kw),
    ))

    reg.register(AgentSpec(
        name="editor_commit",
        role="章节提交编辑",
        description="对草稿做一致性检查、提取元数据、写入 commit（commit_chapter）",
        tools=["commit_chapter", "check_consistency"],
        allowed_next=["supervisor", "editor_review"],
        can_parallel=False,
        llm_role="editor",
        model_capability="review",
        factory=lambda **kw: EditorAgent(**kw),
    ))

    reg.register(AgentSpec(
        name="editor_review",
        role="章节评审",
        description="对已提交章节做评审（save_review），输出 final_verdict",
        tools=["save_review"],
        allowed_next=["supervisor", "writer", "editor_commit"],
        can_parallel=False,
        llm_role="editor",
        model_capability="review",
        factory=lambda **kw: EditorAgent(**kw),
    ))

    reg.register(AgentSpec(
        name="rewrite",
        role="章节重写",
        description="基于评审意见重写或打磨章节（rewrite/polish 模式）",
        tools=["draft_chapter"],
        allowed_next=["editor_commit"],
        can_parallel=False,
        llm_role="rewrite",
        model_capability="longform",
        factory=lambda **kw: RewriteAgent(**kw),
    ))

    reg.register(AgentSpec(
        name="supervisor",
        role="主编调度",
        description=(
            "汇总 commit/review 结果，决定下一步是 review/rewrite/summary/下一章/终止。"
            "调度者本身不直接落库，只返回 next_agent 决策。"
        ),
        tools=[],
        allowed_next=[
            "editor_review", "writer", "rewrite", "architect",
            "arc_summary", "volume_summary", "expand_arc",
            "checkpoint", "FINISH",
        ],
        can_parallel=False,
        llm_role="supervisor",
        model_capability="router",
        factory=lambda **kw: SupervisorAgent(**kw),
    ))

    # 显式预热 common 字典中的 import 绑定（避免 lambda 闭包延迟绑定问题）
    _ = common
    return reg


def build_coordinator_loop(
    cfg: Config,
    store: Store,
    emit_event,
    emit_stream,
):
    from ainovel_py.agents.orchestrator.langgraph.core import LangGraphRuntime

    runner = AgentRunner(build_tool_registry(store))
    return LangGraphRuntime(cfg, runner, store, emit_event, emit_stream)
