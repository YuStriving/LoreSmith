"""阶段 D：ModelRegistry —— 按 capability 选模型。

设计动机：
- 现状：所有 agent 共用 cfg.provider/cfg.model（粗粒度）
- 期望：不同能力（planner/longform/review/...）可用不同模型

设计原则：
1. capability 是字符串标签（如 "planner" / "longform" / "review" / "router" / "default"）
2. ModelSpec 包含 (capability, provider, model)，与 cfg.providers / cfg.provider / cfg.model 完全兼容
3. ModelRegistry.get(capability) 自动 fallback 到 "default" capability（保底）
4. build_default_model_registry 从 cfg.capability_models 构建，未配置时 fallback 到 cfg.provider/cfg.model
5. 零侵入：未配置 capability_models 时，所有 agent 行为与现状完全一致

使用方式：
    reg = ModelRegistry()
    reg.register(ModelSpec(capability="planner", provider="openai", model="gpt-4o-mini"))
    reg.register(ModelSpec(capability="default", provider="deepseek", model="deepseek-chat"))

    spec = reg.get("planner")  # → (openai, gpt-4o-mini)
    spec = reg.get("unknown")  # → fallback 到 default

扩展能力：只需在 cfg.capability_models 增补映射或在 build_default_model_registry 之后
手动 reg.register() 即可，无需修改 BaseAgent.build_client。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ainovel_py.bootstrap.config import Config


@dataclass
class ModelSpec:
    """模型规格：通过 capability 标签匹配 (provider, model)。

    Attributes:
        capability: 能力标签（如 "planner" / "longform" / "review" / "router" / "default"）。
        provider: provider 名称（对应 cfg.providers 中的 key）。
        model: 模型名（如 "gpt-4o-mini" / "deepseek-chat"）。
    """

    capability: str
    provider: str
    model: str

    def __post_init__(self) -> None:
        if not self.capability:
            raise ValueError("ModelSpec.capability is required")
        if not self.provider:
            raise ValueError(f"ModelSpec({self.capability!r}).provider is required")
        if not self.model:
            raise ValueError(f"ModelSpec({self.capability!r}).model is required")


class ModelRegistry:
    """模型注册表：按 capability 标签查找 (provider, model)。

    行为约定：
    - register(spec)：注册一个 capability；同名 capability 重复注册会 raise。
    - get(capability)：capability 命中 → 返回对应 spec；未命中 → fallback 到 "default"；
      连 "default" 都没有 → raise KeyError。
    - has(capability)：判断 capability 是否已注册（不抛异常）。
    - all_capabilities()：返回所有已注册的 capability 列表（按注册顺序）。
    """

    def __init__(self) -> None:
        self._specs: dict[str, ModelSpec] = {}

    def register(self, spec: ModelSpec) -> None:
        """注册一个 ModelSpec。

        Args:
            spec: 模型规格

        Raises:
            ValueError: 必填字段缺失或 capability 重复注册
        """
        if not spec.capability:
            raise ValueError("ModelSpec.capability is required")
        if spec.capability in self._specs:
            raise ValueError(f"capability {spec.capability!r} already registered")
        self._specs[spec.capability] = spec

    def unregister(self, capability: str) -> None:
        """注销一个 capability（用于热更新场景）。"""
        self._specs.pop(capability, None)

    def get(self, capability: str) -> ModelSpec:
        """获取 capability 对应的 ModelSpec，未命中 fallback 到 "default"。

        Args:
            capability: 能力标签

        Returns:
            ModelSpec 实例

        Raises:
            KeyError: capability 未注册且 "default" 也未注册
        """
        spec = self._specs.get(capability)
        if spec is not None:
            return spec
        spec = self._specs.get("default")
        if spec is not None:
            return spec
        raise KeyError(
            f"no model registered for capability {capability!r} "
            f"(available: {list(self._specs.keys())})"
        )

    def has(self, capability: str) -> bool:
        """判断 capability 是否已注册（不抛异常）。"""
        return capability in self._specs

    def all_specs(self) -> list[ModelSpec]:
        """返回所有已注册的 ModelSpec 列表（按注册顺序）。"""
        return list(self._specs.values())

    def all_capabilities(self) -> list[str]:
        """返回所有已注册的 capability 名称列表。"""
        return list(self._specs.keys())


def build_default_model_registry(cfg: Config) -> ModelRegistry:
    """根据 cfg.capability_models 构建 ModelRegistry（未配置时自动注册 default）。

    Args:
        cfg: 系统配置（含 provider / model / providers / capability_models 字段）

    Returns:
        ModelRegistry 实例。保证至少注册了 "default" capability。

    行为约定：
    - cfg.capability_models[cap] = (provider, model) 时注册对应 capability
    - 未配置 capability_models 时，仅注册 "default" → (cfg.provider, cfg.model)
    - capability_models 配置了部分 capability 时，剩余 capability 走 "default" fallback
    """
    reg = ModelRegistry()
    cap_models = getattr(cfg, "capability_models", None) or {}
    for cap, ref in cap_models.items():
        if isinstance(ref, tuple) and len(ref) == 2:
            provider, model = ref
            if provider and model:
                reg.register(ModelSpec(capability=cap, provider=provider, model=model))
    if not reg.has("default"):
        reg.register(
            ModelSpec(capability="default", provider=cfg.provider, model=cfg.model)
        )
    return reg
