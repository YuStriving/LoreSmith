from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from langgraph.graph import END, START, StateGraph

from ainovel_py.host.events import Event

from ..nodes.helpers import _append_line, _is_rewrite_mode, ensure_novel_context
from ..prefetch import get_runtime_cache
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


# ============================================================
# 规划评审常量（可被测试覆盖）
# ============================================================
PLAN_REVIEW_SCORE_THRESHOLD = 3   # score >= 该值视为评审通过
PLAN_REVIEW_MAX_ATTEMPTS = 2      # 最多重试规划次数（防止无限循环）


def build_architect_plan_subgraph(runtime: "LangGraphRuntime") -> Any:
    """构建 Architect 的"规划章节"技能子图。

    子图流程（5 节点 / 1 条件边）：
    START
      → validate_inputs        # 输入校验
      → build_plan             # 规划生成（含 PrefetchPlanCache 优化）
      → review_plan            # 章节计划评审（条件边）
        ├─ 评分 >= 阈值 → normalize_plan
        └─ 评分 < 阈值 & 未超 max → build_plan（循环重试）
      → normalize_plan         # 输出字段规范化
      → END

    validate_inputs 节点：
    - 校验 current_chapter 类型与范围（>= 1）
    - 校验 seed_text / plan_feedback 必须为 str 或 None
    - 软校验：已完成的章节给出告警但不阻塞

    build_plan 节点（优化 ③）：
    - 先查 PrefetchPlanCache，若命中则直接使用（跳过 LLM 调用）
    - 未命中 → 调用 ArchitectAgent.build_dynamic_plan() 生成章节计划
    - 通过 plan_chapter 工具持久化
    - 将计划写入 state["latest_plan"]
    - 命中缓存时同步写一条日志，便于观察"预规划生效"次数

    review_plan 节点（章节规划评审）：
    - 调用 LLM 对 plan 做 5 维度评审（goal / conflict / hook / 一致性 / 字数）
    - score >= 阈值 → 通过
    - score < 阈值 → 写入 plan_feedback，回到 build_plan 循环
    - 超过最大重试次数 → 自动通过（防止无限循环）
    - LLM 调用异常 → 自动通过（不让评审失败阻塞规划）

    normalize_plan 节点：
    - 校验 plan 必填字段（title / goal / conflict / hook / emotion_arc）
    - 缺失字段填默认值
    - 补齐 contract 子结构（min_words / target_words / max_words）
    - 持久化规范化后的 plan

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        编译后的子图，可作为主图的节点使用
    """
    graph = StateGraph(GraphState)
    graph.add_node("validate_inputs", _validate_inputs_node(runtime))
    graph.add_node("build_plan", _build_plan_node(runtime))
    graph.add_node("review_plan", _review_plan_node(runtime))
    graph.add_node("normalize_plan", _normalize_plan_node(runtime))

    graph.add_edge(START, "validate_inputs")
    graph.add_edge("validate_inputs", "build_plan")
    graph.add_edge("build_plan", "review_plan")
    # 条件边：review 通过 → normalize；review 不通过 → 回到 build_plan 循环
    graph.add_conditional_edges(
        "review_plan",
        _should_replan,
        {
            "normalize_plan": "normalize_plan",
            "build_plan": "build_plan",
        },
    )
    graph.add_edge("normalize_plan", END)
    return graph.compile()


def _should_replan(state: GraphState) -> str:
    """条件边路由函数：review 通过则走 normalize，否则回到 build_plan。

    默认 True（auto-approve），保证 review 节点未跑或抛异常时不影响主流程。
    """
    if state.get("_plan_review_approved", True):
        return "normalize_plan"
    return "build_plan"


# ============================================================
# Node 1: validate_inputs —— 输入校验
# ============================================================
def _validate_inputs_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """输入校验节点：拦截非法 state，避免下游 LLM 被坏数据污染。

    校验项：
    1. current_chapter 必须为可转 int 的值，且 >= 1
    2. seed_text / plan_feedback 必须为 str 或 None
    3. 软校验：尝试加载 progress；已完成的章节给出告警但不阻塞（rewrite 模式除外）

    Raises:
        ValueError: 必填项类型/范围错误
        TypeError: 字段类型不匹配
    """
    def _node(state: GraphState) -> GraphState:
        # 1. current_chapter 范围
        ch_raw = state.get("current_chapter")
        if ch_raw is None:
            raise ValueError("current_chapter is required")
        try:
            chapter = int(ch_raw)
        except (TypeError, ValueError) as e:
            raise ValueError(f"current_chapter must be int, got {ch_raw!r}") from e
        if chapter < 1:
            raise ValueError(f"current_chapter must be >= 1, got {chapter}")

        # 2. seed_text / plan_feedback 类型
        for key in ("seed_text", "plan_feedback"):
            v = state.get(key)
            if v is not None and not isinstance(v, str):
                raise TypeError(f"{key} must be str or None, got {type(v).__name__}")

        # 3. 软校验：progress 加载 + 已完成章节告警
        try:
            progress = runtime.store.progress.load()
        except Exception as e:  # noqa: BLE001 —— 软校验失败不阻塞
            _append_line(state, f"[architect] validate: progress load warn: {e}")
            progress = None

        if progress is not None and hasattr(progress, "is_chapter_completed"):
            try:
                if progress.is_chapter_completed(chapter) and not _is_rewrite_mode(progress):
                    _append_line(state, f"[architect] validate warn: ch{chapter} already completed")
            except Exception:  # noqa: BLE001
                pass

        state["_plan_validation_ok"] = True
        _append_line(state, f"[architect] validate_inputs OK ch{chapter}")
        return state

    return _node


# ============================================================
# Node 2: build_plan —— 规划生成（保留原行为）
# ============================================================
def _build_plan_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """Architect 规划技能的核心节点（优化 ③：先查预规划缓存）。

    1. 查 PrefetchPlanCache.get(chapter)
    2. 命中 → 复用 plan，仅写日志 + emit_event，跳过 LLM
    3. 未命中 → 走 ArchitectAgent.build_dynamic_plan() + plan_chapter 工具
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        context = ensure_novel_context(runtime, state)
        seed_text = str(state.get("seed_text") or "")
        feedback = str(state.get("plan_feedback") or "")
        progress = runtime.store.progress.load()

        # 优化 ③：先查预规划缓存
        cache = get_runtime_cache(runtime)
        cached_plan = cache.get(chapter)
        cache_hit = (
            cached_plan is not None
            and not feedback               # 有反馈时强制走 LLM 重新生成
            and not _is_rewrite_mode(progress)
        )
        if cache_hit:
            runtime.emit_event(Event(
                time=datetime.now(),
                category="AGENT",
                summary=f"ArchitectAgent: ch{chapter} plan from PrefetchPlanCache (skip LLM)",
                level="info",
            ))
            _append_line(state, f"[architect] prefetch HIT ch{chapter} -> skip LLM")
            latest_plan = cached_plan
            # 仍然调用 plan_chapter 工具，确保磁盘一致
            try:
                runtime.runner.call_tool("plan_chapter", latest_plan)
            except Exception:
                pass
            state["latest_plan"] = latest_plan
            state["latest_plan_cache_hit"] = True
            # 重置 review_attempts，让缓存命中走完后可正常 review
            state["_plan_review_attempts"] = 0
            return state

        if _is_rewrite_mode(progress):
            summary = f"调用 plan_chapter (rewrite ch{chapter})"
        else:
            summary = f"调用 plan_chapter (ch{chapter})"
        runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=summary, level="info"))

        architect = runtime.get_agent("architect")
        plan_payload = architect.build_dynamic_plan(seed_text, chapter, context, feedback)
        plan_res = runtime.runner.call_tool("plan_chapter", plan_payload)
        latest_plan = plan_res.get("plan") or plan_payload
        state["latest_plan"] = latest_plan
        state["latest_plan_cache_hit"] = False
        # 消费掉本轮 feedback，避免下一轮再触发
        if feedback:
            state["plan_feedback"] = ""
        _append_line(state, f"[architect] plan_chapter -> ch{chapter} title={latest_plan.get('title', '')}")
        return state

    return _node


# ============================================================
# Node 3: review_plan —— 章节计划评审
# ============================================================
def _review_plan_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """章节计划评审节点：调用 LLM 对 plan 做 5 维度评分。

    行为：
    1. 无 plan → 自动通过（前置 build_plan 异常时降级）
    2. 达到最大重试次数 → 自动通过（防止无限循环）
    3. LLM 调用异常 → 自动通过（不让评审失败阻塞规划）
    4. score >= 阈值 → 通过，进入 normalize_plan
    5. score < 阈值 → 写入 plan_feedback，回到 build_plan 循环

    使用 editor agent 的 LLM client（review capability 已经在
    ModelRegistry 中按 capability 路由），未配置 review capability 时
    fallback 到 editor 默认模型。
    """
    def _node(state: GraphState) -> GraphState:
        plan = state.get("latest_plan")
        if not plan:
            state["_plan_review_approved"] = True
            _append_line(state, "[architect] review: no plan, auto-approve")
            return state

        attempts = int(state.get("_plan_review_attempts") or 0)
        if attempts >= PLAN_REVIEW_MAX_ATTEMPTS:
            state["_plan_review_approved"] = True
            _append_line(state, f"[architect] review: max attempts {attempts}, auto-approve")
            return state

        try:
            editor = runtime.get_agent("editor")
            client = editor.build_client()
            score, issues = _call_plan_review(client, plan)
        except Exception as e:  # noqa: BLE001 —— 评审失败不阻塞规划
            _append_line(state, f"[architect] review exception: {e}, auto-approve")
            state["_plan_review_approved"] = True
            return state

        state["_plan_review_score"] = score
        state["_plan_review_issues"] = list(issues)
        state["_plan_review_attempts"] = attempts + 1

        if score >= PLAN_REVIEW_SCORE_THRESHOLD:
            state["_plan_review_approved"] = True
            _append_line(state, f"[architect] review PASS score={score} attempts={attempts + 1}")
        else:
            # 写入 feedback，触发 build_plan 循环
            feedback = "; ".join(issues) if issues else f"plan 评分 {score} 低于阈值 {PLAN_REVIEW_SCORE_THRESHOLD}，请重新规划"
            state["plan_feedback"] = feedback
            state["_plan_review_approved"] = False
            _append_line(state, f"[architect] review FAIL score={score} -> re-plan attempts={attempts + 1}")

        return state

    return _node


def _call_plan_review(client: Any, plan: dict[str, Any]) -> tuple[int, list[str]]:
    """调用 LLM 评审 plan，返回 (score 1-5, issues 列表)。

    评审维度：goal 清晰度 / conflict 强度 / hook 有效性 / 一致性 / 字数合理性。
    低温度 0.2 保证评审结果稳定。

    异常处理由调用方（_review_plan_node）兜底。
    """
    system_prompt = (
        "你是资深小说章节计划评审员，只输出严格 JSON，不要任何额外文字。"
    )
    user_prompt = (
        "请评审以下章节计划，从 5 个维度综合打分 1-5：\n"
        "1) goal 清晰度  2) conflict 强度  3) hook 有效性  4) 与故事一致性  5) 字数合理性\n"
        "score >= 3 视为可写，< 3 视为不合格需返工。\n"
        "issues 数组列出 1-3 条具体问题（合格时可为空数组）。\n\n"
        "严格输出 JSON：\n"
        '{"score": <int 1-5>, "issues": ["问题1", "问题2", ...]}\n\n'
        f"【章节计划】\n{json.dumps(plan, ensure_ascii=False, indent=2)[:3000]}"
    )
    raw = client.complete(system_prompt, user_prompt, temperature=0.2)
    data = json.loads(raw)
    raw_score = int(data.get("score", 3))
    score = max(1, min(5, raw_score))
    issues_raw = data.get("issues") or []
    issues = [str(i).strip() for i in issues_raw if str(i).strip()]
    return score, issues


# ============================================================
# Node 4: normalize_plan —— 输出规范化
# ============================================================
def _normalize_plan_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """输出规范化节点：补齐 plan 必填字段默认值，持久化到磁盘。

    规范化项：
    - 必填字符串字段：title / goal / conflict / hook / emotion_arc
    - contract 子结构：min_words / target_words / max_words
    - 持久化：调用 plan_chapter 工具，覆盖磁盘上残缺 plan
    """
    def _node(state: GraphState) -> GraphState:
        plan = state.get("latest_plan")
        if not plan:
            _append_line(state, "[architect] normalize: no plan to normalize")
            state["_plan_normalized"] = False
            return state

        normalized_count = 0
        chapter = plan.get("chapter") or state.get("current_chapter") or "?"

        # 必填字符串字段
        required_defaults = {
            "title": f"第{chapter}章",
            "goal": "推进主线冲突并制造新的局面",
            "conflict": "角色在压力中做出高代价选择",
            "hook": "章末引出更大问题",
            "emotion_arc": "承压 -> 升级 -> 反转/悬念",
        }
        for key, default in required_defaults.items():
            if not str(plan.get(key, "")).strip():
                plan[key] = default
                normalized_count += 1
                _append_line(state, f"[architect] normalized: {key} -> default")

        # contract 子结构
        contract = plan.setdefault("contract", {})
        if not isinstance(contract, dict):
            plan["contract"] = {}
            contract = plan["contract"]
        if int(contract.get("min_words", 0) or 0) <= 0:
            contract["min_words"] = 1200
            normalized_count += 1
        target = int(contract.get("target_words", 0) or 0)
        if target <= 0:
            contract["target_words"] = 1800
            target = 1800
            normalized_count += 1
        if int(contract.get("max_words", 0) or 0) < target:
            contract["max_words"] = max(target + 400, 2200)
            normalized_count += 1

        # 持久化规范化后的 plan
        try:
            runtime.runner.call_tool("plan_chapter", plan)
        except Exception as e:  # noqa: BLE001
            _append_line(state, f"[architect] normalize persist warn: {e}")

        state["latest_plan"] = plan
        state["_plan_normalized"] = normalized_count > 0
        _append_line(state, f"[architect] normalized {normalized_count} fields")
        return state

    return _node
