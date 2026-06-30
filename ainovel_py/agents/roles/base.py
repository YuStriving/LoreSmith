from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from ainovel_py.agents.context_manager import ContextManager
from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.agents.model_registry import ModelRegistry, build_default_model_registry
from ainovel_py.agents.runner import AgentRunner
from ainovel_py.assets import AssetBundle
from ainovel_py.bootstrap.config import Config
from ainovel_py.store.store import Store


class BaseAgent(ABC):
    name: str = ""
    model_capability: str = "default"     # 阶段 D：子类按需覆盖（"planner"/"longform"/"review"/"router"）

    def __init__(
        self,
        cfg: Config,
        runner: AgentRunner,
        store: Store,
        assets: AssetBundle,
        emit_event: Callable[[Any], None],
        emit_stream: Callable[[str, str], None],
    ) -> None:
        self.cfg = cfg
        self.runner = runner
        self.store = store
        self.assets = assets
        self.emit_event = emit_event
        self.emit_stream = emit_stream
        self.context_manager = ContextManager(context_window=cfg.context_window)
        # 阶段 D：注入 ModelRegistry（从 cfg.capability_models 构造）
        self.model_registry: ModelRegistry = build_default_model_registry(cfg)

    @abstractmethod
    def system_prompt(self) -> str: ...

    @abstractmethod
    def execute(self, **kwargs) -> dict[str, Any]: ...

    def build_client(self, capability: str | None = None) -> OpenAICompatClient:
        """阶段 D：按 capability 标签动态选模型，未指定 capability 时取 self.model_capability。

        行为约定：
        - capability=None → 使用 self.model_capability
        - capability="xxx" → 优先匹配 capability_models["xxx"]，未命中 fallback 到 "default"
        - cfg.capability_models 未配置时，所有 capability 走 default = (cfg.provider, cfg.model)
        - 与旧版完全兼容：默认 BaseAgent.model_capability = "default"，行为零变化
        """
        cap = capability or self.model_capability
        spec = self.model_registry.get(cap)
        provider_name = spec.provider
        model_name = spec.model

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
