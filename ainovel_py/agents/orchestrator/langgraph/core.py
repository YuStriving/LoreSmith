from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from langgraph.graph import END, START, StateGraph

from ainovel_py.agents.orchestrator.registry import AgentRegistry
from ainovel_py.agents.context_manager import ContextManager
from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.agents.roles import ArchitectAgent, BaseAgent, EditorAgent, RewriteAgent, SupervisorAgent, WriterAgent
from ainovel_py.agents.runner import AgentRunner
from ainovel_py.agents.orchestrator.interface import OrchestratorBackend
from ainovel_py.agents.orchestrator.dispatcher import dispatch_next, dispatch_next_v2
from ainovel_py.agents.orchestrator.tags import TaskTag
from ainovel_py.assets import load_bundle
from ainovel_py.bootstrap.config import Config
from ainovel_py.domain.writing import PendingRunCheckpoint
from ainovel_py.host.events import Event
from ainovel_py.store.store import Store

from .nodes import (
    checkpoint_node,
    finish_node,
    load_runtime_context,
    route_after_checkpoint,
    route_after_load,
    supervisor_node,
)
from .nodes.helpers import _append_line, _execute_parallel_summaries, is_parallel_summary_set, route_from_supervisor
from .state import GraphState, OrchestratorState
from .subgraphs import (
    build_architect_plan_subgraph,
    build_editor_commit_subgraph,
    build_editor_review_subgraph,
    build_summary_subgraph,
    build_writer_subgraph,
)

# TaskTag 到子图节点名的映射
TAG_TO_NODE: dict[str, str] = {
    TaskTag.PLAN_CHAPTER.value: "architect_plan",
    TaskTag.WRITE_CHAPTER.value: "writer_write",
    TaskTag.COMMIT_CHAPTER.value: "editor_commit",
    TaskTag.REVIEW_CHAPTER.value: "editor_review",
    TaskTag.REWRITE_CHAPTER.value: "writer_write",
    TaskTag.ARC_SUMMARY.value: "architect_summary",
    TaskTag.VOLUME_SUMMARY.value: "architect_summary",
    TaskTag.EXPAND_ARC.value: "architect_summary",
    TaskTag.FINISH.value: "finish",
}


# 阶段 B：AgentSpec.name → 子图节点名 的映射
# dispatch_next_v2 返回 agent name（而非 TaskTag），由 _route_by_agent_name 翻译到子图节点。
AGENT_TO_NODE: dict[str, str] = {
    "architect":      "architect_plan",
    "writer":         "writer_write",
    "editor_commit":  "editor_commit",
    "editor_review":  "editor_review",
    "rewrite":        "writer_write",       # rewrite 与 writer 共享子图
    "arc_summary":    "architect_summary",
    "volume_summary": "architect_summary",
    "expand_arc":     "architect_summary",
    "checkpoint":     "checkpoint",
    "supervisor":     "checkpoint",         # supervisor 不直接跳到子图，由 supervisor_node 处理；兜底回 dispatch
    "FINISH":         "finish",
}


@dataclass
class LangGraphRuntime(OrchestratorBackend):
    cfg: Config
    runner: AgentRunner
    store: Store
    emit_event: Callable[[Event], None]
    emit_stream: Callable[[str, str], None]

    def __post_init__(self) -> None:
        self._aborted = False
        self.context_manager = ContextManager(context_window=self.cfg.context_window)
        self.assets = load_bundle(self.cfg.style)
        # 阶段 A：先构建 Agent 注册表，再按 factory 实例化。
        # 这样可以保证 _build_graph 之前所有 agent 已就绪。
        self.registry: AgentRegistry = self._build_registry()
        self._agents: dict[str, BaseAgent] = {}
        self._init_agents_via_registry()
        self.graph = self._build_graph()

    def _build_registry(self) -> AgentRegistry:
        """构建 Agent 注册表，注入所有角色的元数据。

        注册表只保存元数据（spec），不保存实例。实例化在 _init_agents_via_registry 完成。
        这样可以让"能力扩展"只改本函数（register 一行），不改 dispatcher 或图拓扑。
        """
        from ainovel_py.agents.build import build_agent_registry

        return build_agent_registry(
            cfg=self.cfg,
            store=self.store,
            runner=self.runner,
            assets=self.assets,
            emit_event=self.emit_event,
            emit_stream=self.emit_stream,
        )

    def _init_agents_via_registry(self) -> None:
        """根据注册表的 spec.factory 实例化所有 agent。

        与原 _init_agents 行为完全一致，但通过 registry 间接获取 spec，
        保留向后兼容：self._agents 仍是 dict[str, BaseAgent]。
        """
        common = dict(
            cfg=self.cfg,
            runner=self.runner,
            store=self.store,
            assets=self.assets,
            emit_event=self.emit_event,
            emit_stream=self.emit_stream,
        )
        for spec in self.registry.all_specs():
            if spec.factory is None:
                # 元数据型 spec（如纯注册，无实例）跳过
                continue
            self._agents[spec.name] = spec.factory(**common)

    def get_agent(self, name: str) -> BaseAgent:
        return self._agents[name]

    def _build_llm_for_role(self, role: str) -> OpenAICompatClient:
        """为指定 role 构造 LLM 客户端（用于阶段 B 的 LLM 决策调用）。

        优先查找 cfg.roles[role]，无则回退到 cfg.provider/cfg.model 默认配置。
        role 通常为 "supervisor"（dispatch 决策的默认调用方）。
        """
        rc = self.cfg.roles.get(role)
        if rc and rc.provider and rc.model:
            provider_name = rc.provider
            model_name = rc.model
        else:
            provider_name = self.cfg.provider
            model_name = self.cfg.model
        pc = self.cfg.providers.get(provider_name)
        if pc is None or not pc.api_key:
            raise RuntimeError(f"provider {provider_name} api_key 未配置")
        key_norm = pc.api_key.strip().lower()
        if key_norm in {"dummy-key", "dummy", "test", "placeholder", "changeme"}:
            raise RuntimeError(f"provider {provider_name} api_key 为占位值")
        return OpenAICompatClient(
            api_key=pc.api_key,
            model=model_name,
            base_url=pc.base_url,
            timeout=120.0,
        )

    def start(self, prompt: str) -> None:
        self._aborted = False
        self._invoke(prompt, resume_mode=False)

    def resume(self, prompt: str) -> None:
        self._aborted = False
        self._invoke(prompt, resume_mode=True)

    def follow_up(self, text: str) -> None:
        self._aborted = False
        self._invoke(text, resume_mode=False)

    def abort(self) -> None:
        self._aborted = True

    def wait_idle(self) -> None:
        return

    @property
    def is_aborted(self) -> bool:
        return self._aborted

    def emit_checkpoint_pending(self, pending: PendingRunCheckpoint) -> None:
        pass

    def _invoke(self, seed_text: str, resume_mode: bool) -> None:
        state: OrchestratorState = {
            "seed_text": seed_text,
            "resume_mode": resume_mode,
            "pending_action": "load",
            "pending_actions": [],
            "stop_requested": self._aborted,
            "out_lines": [f"[LangGraph] 协调器开始执行：{seed_text}"],
        }
        result = self.graph.invoke(state)
        out_lines = result.get("out_lines") or []
        if out_lines:
            self.emit_stream("thinking", "\n".join(out_lines) + "\n")

    def build_client(self) -> OpenAICompatClient:
        pc = self.cfg.providers.get(self.cfg.provider)
        if pc is None or not pc.api_key:
            raise RuntimeError(f"provider {self.cfg.provider} api_key 未配置")
        key_norm = pc.api_key.strip().lower()
        if key_norm in {"dummy-key", "dummy", "test", "placeholder", "changeme"}:
            raise RuntimeError(f"provider {self.cfg.provider} api_key 为占位值")
        return OpenAICompatClient(
            api_key=pc.api_key,
            model=self.cfg.model,
            base_url=pc.base_url,
            timeout=120.0,
        )

    def _build_graph(self):
        """构建主图 + 子图的二级架构。

        主图结构（角色编排层，阶段 C 改造后）：
        START → load_context → dispatch → [角色子图] → collect → supervisor → dispatch (循环)
                        ↓                                          ↓           ↓
                      finish                                    checkpoint → supervisor → ... → finish → END

        supervisor 节点作为必经路由点：所有 collect 节点 + 所有 checkpoint 节点后
        都经过 supervisor，由 LLM 决定下一目标。

        子图结构（技能实现层）：
        - architect_plan: Architect 的规划章节技能
        - writer_write: Writer 的写章节技能
        - editor_commit: Editor 的提交章节技能
        - editor_review: Editor 的评审章节技能
        - architect_summary: Architect 的弧/卷摘要技能

        上下文加载策略：懒加载。子图按需调用 ensure_novel_context() 加载上下文，
        首次加载后缓存到 state["context"]，后续子图直接复用。
        """
        graph = StateGraph(OrchestratorState)

        # === 主图节点（角色编排层） ===
        graph.add_node("load_context", load_runtime_context(self))
        graph.add_node("dispatch", _dispatch_node(self))
        graph.add_node("collect", _collect_node(self))
        # 阶段 C：supervisor 提升为必经路由点
        graph.add_node("supervisor", supervisor_node(self))
        # 优化 ①-2：并行 summary 节点（处理 commit 后置任务并行）
        graph.add_node("parallel_summaries", _parallel_summary_node(self))
        graph.add_node("checkpoint", checkpoint_node(self))
        graph.add_node("finish", finish_node(self))

        # === 角色技能子图节点 ===
        graph.add_node("architect_plan", build_architect_plan_subgraph(self))
        graph.add_node("writer_write", build_writer_subgraph(self))
        graph.add_node("editor_commit", build_editor_commit_subgraph(self))
        graph.add_node("editor_review", build_editor_review_subgraph(self))
        graph.add_node("architect_summary", build_summary_subgraph(self))

        # === 边 ===
        graph.add_edge(START, "load_context")

        # load_context → 根据恢复状态决定：dispatch 或 finish
        graph.add_conditional_edges(
            "load_context",
            _route_after_load_to_dispatch,
            {
                "dispatch": "dispatch",
                "finish": "finish",
            },
        )

        # dispatch → 根据 agent name 路由到角色子图（阶段 B）
        graph.add_conditional_edges(
            "dispatch",
            _route_by_agent_name,
            {
                "architect_plan": "architect_plan",
                "writer_write": "writer_write",
                "editor_commit": "editor_commit",
                "editor_review": "editor_review",
                "architect_summary": "architect_summary",
                "checkpoint": "checkpoint",
                "finish": "finish",
            },
        )

        # 阶段 C：所有角色子图完成后都先回到 supervisor（必经路由点）
        graph.add_edge("architect_plan", "collect")
        graph.add_edge("writer_write", "collect")
        graph.add_edge("editor_commit", "collect")
        graph.add_edge("editor_review", "collect")
        graph.add_edge("architect_summary", "collect")

        # 优化 ①-2：collect → 根据 pending_actions 是否为并行 summary 集合决定路由
        #   - 是 → parallel_summaries
        #   - 否 → supervisor（必经）
        graph.add_conditional_edges(
            "collect",
            _route_after_collect_to_parallel,
            {
                "parallel_summaries": "parallel_summaries",
                "supervisor": "supervisor",
            },
        )

        # 优化 ①-2：parallel_summaries → supervisor（必经）
        graph.add_edge("parallel_summaries", "supervisor")

        # 阶段 C：checkpoint → supervisor（必经）
        graph.add_edge("checkpoint", "supervisor")

        # supervisor → 根据 LLM 决策路由到目标节点
        graph.add_conditional_edges(
            "supervisor",
            route_from_supervisor,
            {
                "architect_plan":   "architect_plan",
                "writer_write":     "writer_write",
                "editor_commit":    "editor_commit",
                "editor_review":    "editor_review",
                "architect_summary":"architect_summary",
                "novel_context":    "dispatch",       # supervisor 选 novel_context → 回到 dispatch 重新决策
                "generate_draft":   "dispatch",       # 兼容旧的 generate_draft 决策
                "review":           "editor_review",  # review 直接跳到评审子图
                "rewrite":          "writer_write",   # rewrite 走 writer 子图
                "arc_summary":      "architect_summary",
                "volume_summary":   "architect_summary",
                "expand_arc":       "architect_summary",
                "checkpoint":       "checkpoint",
                "finish":           "finish",
                # 兜底：回到 dispatch 重新决策
                "dispatch":         "dispatch",
            },
        )

        graph.add_edge("finish", END)

        return graph.compile()


# ============================================================
# 主图节点实现
# ============================================================

# 主图全局迭代上限（防死循环安全网）
MAX_GRAPH_ITERATIONS = 30

# 连续无章节进展的硬性兜底（spec: langgraph-no-infinite-loop）
# 如果连续 N 轮主图迭代没有任何章节完成（completed_chapters 数量未变），
# 强制 finish 并 emit task_stalled 事件，供前端接管。
MAX_CONSECUTIVE_IDLE_ROUNDS = 3


def _check_task_completed(runtime: "LangGraphRuntime", state: OrchestratorState) -> bool:
    """通过进度状态判断当前创作需求是否已完成。

    判断逻辑（任一满足即视为完成）：
    1. 所有章节已写完（progress.completed_chapters 覆盖 total_chapters）
    2. 无进度数据且迭代超过 3 次（异常状态，安全退出）
    3. runtime 已被外部中止
    """
    if runtime.is_aborted:
        return True
    progress = runtime.store.progress.load()
    if progress and progress.total_chapters > 0:
        completed = set(progress.completed_chapters) if progress.completed_chapters else set()
        if len(completed) >= progress.total_chapters:
            return True
    iteration = int(state.get("_graph_iteration") or 0)
    if not progress and iteration > 3:
        return True
    return False


def _check_idle_stall(runtime: "LangGraphRuntime", state: OrchestratorState) -> bool:
    """检查是否连续 N 轮无进展（spec: langgraph-no-infinite-loop 业务层兜底）。

    返回 True 表示已触发 idle stall，需要强制 finish。
    """
    progress = runtime.store.progress.load()
    current_completed = max(progress.completed_chapters) if (progress and progress.completed_chapters) else 0
    last_completed = int(state.get("_last_completed_count") or 0)
    if current_completed > last_completed:
        # 有进展 → 重置 idle_rounds
        state["_last_completed_count"] = current_completed
        state["_idle_rounds"] = 0
        return False
    # 无进展 → 累加 idle_rounds
    idle_rounds = int(state.get("_idle_rounds") or 0) + 1
    state["_idle_rounds"] = idle_rounds
    return idle_rounds >= MAX_CONSECUTIVE_IDLE_ROUNDS


def _dispatch_node(runtime: "LangGraphRuntime") -> Callable[[OrchestratorState], OrchestratorState]:
    """主 Agent 的 dispatch 节点：分析状态，决定任务分配给哪个角色（阶段 C：supervisor 短路）。

    阶段 C 行为：
    - 如果上一轮 supervisor 已产生 supervisor_decision（通过 _route_from_supervisor 映射到下一个目标 agent），
      则 dispatch 不再调 LLM，直接消费 supervisor_decision。
    - 否则（首次启动 / 流程入口 / supervisor 决策为 "dispatch"），正常执行 dispatch_next_v2。

    死循环防护：
    - 每次进入 dispatch 递增 _graph_iteration
    - 先检查 _check_task_completed（需求是否已完成）
    - 超过 MAX_GRAPH_ITERATIONS 硬上限时强制 finish
    """
    def _node(state: OrchestratorState) -> OrchestratorState:
        # 递增迭代计数器
        iteration = int(state.get("_graph_iteration") or 0) + 1
        state["_graph_iteration"] = iteration

        # P1-001 修复：dispatch 正常执行时重置 checkpoint 访问计数
        state["_checkpoint_visits"] = 0

        # 安全网0：连续无进展兜底（spec: langgraph-no-infinite-loop 业务层）
        # 连续 3 轮主图迭代没有任何章节完成 → 强制 finish + emit task_stalled
        if _check_idle_stall(runtime, state):
            state["current_tag"] = "FINISH"
            state["pending_action"] = "finish"
            state["dispatch_reason"] = f"idle_stall rounds={state.get('_idle_rounds')}"
            _append_line(
                state,
                f"[dispatch] IDLE STALL -> finish (iter={iteration}, "
                f"idle_rounds={state.get('_idle_rounds')}, "
                f"last_completed={state.get('_last_completed_count')})"
            )
            try:
                from datetime import datetime
                runtime.emit_event(Event(
                    time=datetime.now(),
                    category="AGENT",
                    summary="task_stalled: no chapter progress for 3 iterations, awaiting user takeover",
                    level="warning",
                ))
            except Exception:
                pass
            return state

        # 安全网1：需求完成检查（所有章节写完 → 自动退出）
        if _check_task_completed(runtime, state):
            state["current_tag"] = "FINISH"
            state["pending_action"] = "finish"
            state["dispatch_reason"] = f"task_completed iter={iteration}"
            _append_line(state, f"[dispatch] TASK COMPLETED -> finish (iter={iteration})")
            return state

        # 安全网2：硬迭代上限（防死循环兜底）
        if iteration > MAX_GRAPH_ITERATIONS:
            state["current_tag"] = "FINISH"
            state["pending_action"] = "finish"
            state["dispatch_reason"] = f"max_iterations={MAX_GRAPH_ITERATIONS}"
            _append_line(state, f"[dispatch] MAX ITERATIONS HIT -> finish (iter={iteration})")
            return state

        # 阶段 C：如果 supervisor 已决策，复用其结果，避免重复 LLM 调用
        supervisor_decision = state.get("supervisor_decision")
        if supervisor_decision and isinstance(supervisor_decision, dict):
            agent_name = str(supervisor_decision.get("next_agent") or "")
            # 标准化：supervisor 内部使用的 "architect" / "writer" 等已是 agent name
            state["current_tag"] = agent_name
            reason = (
                f"last={state.get('last_completed_tag', 'none')} "
                f"pending={state.get('pending_action', 'none')} "
                f"supervisor_decision={agent_name}"
            )
            state["dispatch_reason"] = reason
            _append_line(state, f"[dispatch] cached_supervisor agent={agent_name} reason={reason}")
            # 消费完 supervisor_decision，清空避免下次重复消费
            state["supervisor_decision"] = None
            return state

        # 阶段 B：尝试构造 supervisor 角色的 LLM 客户端；构造失败时退回纯规则
        llm_client = None
        try:
            llm_client = runtime._build_llm_for_role("supervisor")
        except Exception:
            llm_client = None  # 退回 v1 纯规则

        # 阶段 B：用 dispatch_next_v2（规则 + LLM 兜底）
        agent_name = dispatch_next_v2(
            state=state,
            registry=runtime.registry,
            llm_client=llm_client,
            log_path=None,         # 可改为实际路径启用 LLM 决策日志
        )
        state["current_tag"] = agent_name     # 存 agent name（阶段 B 改造）
        reason = (
            f"last={state.get('last_completed_tag', 'none')} "
            f"pending={state.get('pending_action', 'none')}"
        )
        state["dispatch_reason"] = reason
        _append_line(state, f"[dispatch] agent={agent_name} reason={reason}")
        return state
    return _node


def _collect_node(runtime: "LangGraphRuntime") -> Callable[[OrchestratorState], OrchestratorState]:
    """主 Agent 的 collect 节点：收集角色子图产出，更新状态（阶段 C 简化）。

    阶段 C 行为：
    - 只更新 last_completed_tag，**不再修改 pending_action**
    - pending_action 决策由 supervisor 统一处理
    - 子图设置的 pending_action（如 review 后的 rewrite）保留，让 supervisor 看到
    """
    def _node(state: OrchestratorState) -> OrchestratorState:
        completed_tag = str(state.get("current_tag") or "")
        state["last_completed_tag"] = completed_tag
        _append_line(state, f"[collect] completed={completed_tag}")
        # 阶段 C：pending_action 由 supervisor 决定，collect 不再修改
        return state
    return _node


def _parallel_summary_node(runtime: "LangGraphRuntime") -> Callable[[OrchestratorState], OrchestratorState]:
    """优化 ①-2：并行执行 commit 后置 summary 任务的节点工厂。

    工作流程：
    1. 从 state["pending_actions"] 读取待执行任务
    2. 调用 _execute_parallel_summaries 并行执行
    3. 消费 pending_actions 队列
    4. 设置 last_completed_tag 供 supervisor 决策
    """
    def _node(state: OrchestratorState) -> OrchestratorState:
        tasks = list(state.get("pending_actions") or [])
        _append_line(state, f"[parallel_summaries] start tasks={tasks}")
        result = _execute_parallel_summaries(runtime, state, tasks)
        # 消费已执行的 task
        for task in tasks:
            current = list(state.get("pending_actions") or [])
            if current and current[0] == task:
                current.pop(0)
                state["pending_actions"] = current
        # 标记本次完成的 tag 为 "parallel_summaries"
        state["current_tag"] = "parallel_summaries"
        state["last_completed_tag"] = "parallel_summaries"
        _append_line(state, f"[parallel_summaries] done all_ok={result.get('all_ok')}")
        return state
    return _node


def _route_after_collect_to_parallel(state: OrchestratorState) -> str:
    """优化 ①-2：collect 后的路由：决定进入 parallel_summaries 还是 supervisor。

    判断逻辑：
    - 如果 state["pending_actions"] 全部为 summary 任务（arc_summary / volume_summary / expand_arc），
      且长度 > 1，则路由到 parallel_summaries
    - 否则路由到 supervisor（阶段 C 必经）
    """
    pending = list(state.get("pending_actions") or [])
    if is_parallel_summary_set(pending):
        return "parallel_summaries"
    return "supervisor"


# ============================================================
# 路由函数
# ============================================================

def _route_after_load_to_dispatch(state: OrchestratorState) -> str:
    """load_context 后的路由：决定进入 dispatch 还是 finish。"""
    action = str(state.get("pending_action") or "dispatch")
    if action == "finish":
        return "finish"
    return "dispatch"


def _route_by_tag(state: OrchestratorState) -> str:
    """根据 current_tag（TaskTag.value）路由到对应的角色子图节点。

    v1 旧接口，保留向后兼容。阶段 B 后推荐使用 _route_by_agent_name。
    """
    tag = str(state.get("current_tag") or "")
    node = TAG_TO_NODE.get(tag)
    if node:
        return node
    # 未知 tag → 回到 dispatch 重新决策
    return "dispatch"


def _route_by_agent_name(state: OrchestratorState) -> str:
    """根据 current_tag（agent name）路由到对应的角色子图节点（阶段 B 新增）。"""
    agent_name = str(state.get("current_tag") or "")
    node = AGENT_TO_NODE.get(agent_name)
    if node:
        return node
    # 未知 agent name → 回到 dispatch 重新决策
    return "dispatch"


def _route_after_collect(state: OrchestratorState) -> str:
    """collect 后的路由（阶段 C 之后已不直接调用，保留向后兼容）。

    阶段 C 改造后 collect → supervisor 是固定边，不再需要条件路由。
    此函数保留以备回退/调试使用。
    """
    pending_action = str(state.get("pending_action") or "")
    if pending_action == "finish":
        return "checkpoint"
    if pending_action == "checkpoint":
        return "checkpoint"
    # 默认继续 dispatch（循环）
    return "dispatch"


def _route_after_checkpoint_to_dispatch(state: OrchestratorState) -> str:
    """checkpoint 后的路由（阶段 C 之后已不直接调用，保留向后兼容）。

    阶段 C 改造后 checkpoint → supervisor 是固定边，supervisor 决定下一步。
    """
    action = str(state.get("pending_action") or "finish")
    if action in ("novel_context", "continue"):
        # checkpoint 决定继续下一章 → 重新 dispatch
        state["last_completed_tag"] = ""
        return "dispatch"
    if action == "finish":
        return "finish"
    # 其他情况也回到 dispatch
    return "dispatch"
