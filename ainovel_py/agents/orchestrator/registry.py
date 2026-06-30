"""AgentRegistry: 多 Agent 自主编排的统一注册中心。

该模块提供：
- AgentSpec：Agent 元数据（description / tools / allowed_next / can_parallel / model_capability）。
- AgentRegistry：注册表的增删查 + 白名单过滤。

设计原则：
1. 显式注册：所有 Agent 通过 register() 显式登记，提供 LLM 决策所需的元数据。
2. 静态元数据：description/tools/allowed_next 等在注册时声明，运行时不可变。
3. 工厂延迟实例化：factory 字段保存构造闭包，运行时按需创建实例。

使用方式：
    reg = AgentRegistry()
    reg.register(AgentSpec(name="architect", description="...", tools=[...], ...))
    spec = reg.get("architect")
    for s in reg.all_specs():
        ...
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AgentSpec:
    """Agent 注册元数据：描述、能力、上游白名单、是否可并行。

    Attributes:
        name: 唯一标识（如 "architect"/"writer"/"editor_commit"）。
        role: 人类可读身份（如 "章节规划师"）。
        description: 告诉 LLM "我是谁、能做什么"，作为 LLM 路由 prompt 的输入。
        tools: 该 Agent 可调用的工具名白名单。
        allowed_next: 上游可调用本 Agent 的 agent 名称列表（用于 LLM 决策时的白名单过滤）。
        can_parallel: 是否可与其他 agent 并行（用于 LLM 决策时识别"独立任务"）。
        llm_role: 绑定 cfg.roles[key]，指定该 Agent 默认使用的角色配置。
        model_capability: 模型能力标签（如 "planner"/"longform"/"review"/"summarizer"），
            与 ModelRegistry 配合实现按能力选模型。
        factory: 构造 agent 实例的工厂函数，签名为 (**kwargs) -> BaseAgent。
            运行时通过 factory(cfg=..., runner=..., ...) 构造。
    """

    name: str
    role: str
    description: str
    tools: list[str] = field(default_factory=list)
    allowed_next: list[str] = field(default_factory=list)
    can_parallel: bool = False
    llm_role: str = ""
    model_capability: str = "default"
    factory: Callable[..., Any] | None = None


class AgentRegistry:
    """Agent 注册表：维护所有可用 Agent 的元数据。

    提供 LLM 决策所需的查询接口：
    - get(name) → 查单个 spec
    - all_specs() → 列全部 spec（用于构造 LLM prompt）
    - allowed_targets(from_agent) → 列出从 from_agent 出发可达的下一跳 agent
    """

    def __init__(self) -> None:
        self._specs: dict[str, AgentSpec] = {}

    def register(self, spec: AgentSpec) -> None:
        """注册一个 Agent spec。

        Args:
            spec: Agent 元数据

        Raises:
            ValueError: 同名 Agent 重复注册
            ValueError: 必填字段缺失（name/role/description 为空）
        """
        if not spec.name:
            raise ValueError("AgentSpec.name is required")
        if not spec.role:
            raise ValueError(f"AgentSpec({spec.name}).role is required")
        if not spec.description:
            raise ValueError(f"AgentSpec({spec.name}).description is required")
        if spec.name in self._specs:
            raise ValueError(f"agent {spec.name} already registered")
        self._specs[spec.name] = spec

    def unregister(self, name: str) -> None:
        """注销一个 Agent（用于热插拔场景）。

        Args:
            name: Agent 名称
        """
        self._specs.pop(name, None)

    def get(self, name: str) -> AgentSpec:
        """获取指定 Agent 的 spec。

        Args:
            name: Agent 名称

        Returns:
            AgentSpec 实例

        Raises:
            KeyError: Agent 未注册
        """
        if name not in self._specs:
            raise KeyError(f"unknown agent: {name}")
        return self._specs[name]

    def has(self, name: str) -> bool:
        """判断 Agent 是否已注册（不抛异常）。"""
        return name in self._specs

    def all_specs(self) -> list[AgentSpec]:
        """列出全部 Agent spec。

        Returns:
            全部 spec 列表（按注册顺序）
        """
        return list(self._specs.values())

    def all_names(self) -> list[str]:
        """列出全部 Agent 名称。"""
        return list(self._specs.keys())

    def allowed_targets(self, from_agent: str) -> list[str]:
        """列出从 from_agent 出发可达的下一跳 agent 列表。

        用于 LLM 决策时的白名单过滤——LLM 只能选 from_agent.allowed_next 中的 agent。

        Args:
            from_agent: 当前 agent 名（空字符串表示流程入口）

        Returns:
            允许的下一跳 agent 名称列表
        """
        if not from_agent:
            # 流程入口：返回除 supervisor 之外的全部 agent
            return [n for n in self._specs.keys() if n != "supervisor"]
        if from_agent not in self._specs:
            # 未知 agent：返回全部（保持兼容性，避免死锁）
            return [n for n in self._specs.keys() if n != "supervisor"]
        return list(self._specs[from_agent].allowed_next)

    def filter_candidates(
        self,
        from_agent: str,
        exclude: set[str] | None = None,
    ) -> list[str]:
        """根据 from_agent 白名单 + 排除集合过滤候选 agent。

        Args:
            from_agent: 当前 agent 名
            exclude: 额外排除的 agent 名集合

        Returns:
            过滤后的候选 agent 名称列表
        """
        allowed = self.allowed_targets(from_agent)
        excl = exclude or set()
        return [a for a in allowed if a not in excl]
