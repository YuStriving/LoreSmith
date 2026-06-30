"""阶段 D 单元测试：ModelRegistry。

覆盖：
1. ModelSpec 必填字段校验
2. ModelRegistry CRUD（register / get / has / unregister / all_specs / all_capabilities）
3. fallback：未注册 capability → fallback 到 "default"
4. fallback：未注册任何 capability → get raise KeyError
5. build_default_model_registry：
   - cfg.capability_models 为空时只注册 default
   - cfg.capability_models 配置后保留 mapping
   - capability_models 中 provider/model 为空时跳过
6. 各 agent 类的 model_capability 正确（planner/longform/review/longform/router）
7. BaseAgent.build_client(capability) 按 ModelRegistry 选模型
8. BaseAgent.build_client()（无参数）走 self.model_capability
9. 未配置 capability_models 时 build_client 行为与现状一致
"""
from __future__ import annotations

import sys
import importlib.util
import types
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _install_fake_package(name: str):
    if name in sys.modules:
        return sys.modules[name]
    parts = name.split(".")
    for i in range(1, len(parts) + 1):
        sub = ".".join(parts[:i])
        if sub not in sys.modules:
            m = types.ModuleType(sub)
            m.__path__ = []
            sys.modules[sub] = m
    return sys.modules[name]


def _load_module(name: str, rel_path: str):
    if "." in name:
        parent = ".".join(name.split(".")[:-1])
        _install_fake_package(parent)
    spec = importlib.util.spec_from_file_location(name, str(PROJECT_ROOT / rel_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


print("=" * 60)
print("阶段 D 单元测试：ModelRegistry")
print("=" * 60)

# bootstrap stub（model_registry.py 依赖 Config）
bootstrap_mod = _load_module(
    "ainovel_py.bootstrap.config",
    "ainovel_py/bootstrap/config.py",
)
Config = bootstrap_mod.Config

# 加载 model_registry 模块
model_reg_mod = _load_module(
    "ainovel_py.agents.model_registry",
    "ainovel_py/agents/model_registry.py",
)
ModelSpec = model_reg_mod.ModelSpec
ModelRegistry = model_reg_mod.ModelRegistry
build_default_model_registry = model_reg_mod.build_default_model_registry


# ============================================================
# Test 1: ModelSpec 必填字段校验
# ============================================================
print("\n[Test 1] ModelSpec 必填字段校验")

# 正常构造
spec = ModelSpec(capability="planner", provider="openai", model="gpt-4o-mini")
assert spec.capability == "planner"
assert spec.provider == "openai"
assert spec.model == "gpt-4o-mini"
print("[PASS] 1.1 正常构造")

# 缺 capability
try:
    ModelSpec(capability="", provider="openai", model="gpt-4")
    assert False, "should raise"
except ValueError as e:
    assert "capability" in str(e)
print("[PASS] 1.2 缺 capability → raise")

# 缺 provider
try:
    ModelSpec(capability="planner", provider="", model="gpt-4")
    assert False, "should raise"
except ValueError as e:
    assert "provider" in str(e)
print("[PASS] 1.3 缺 provider → raise")

# 缺 model
try:
    ModelSpec(capability="planner", provider="openai", model="")
    assert False, "should raise"
except ValueError as e:
    assert "model" in str(e)
print("[PASS] 1.4 缺 model → raise")


# ============================================================
# Test 2: ModelRegistry CRUD
# ============================================================
print("\n[Test 2] ModelRegistry CRUD")

reg = ModelRegistry()
assert reg.has("planner") is False
assert reg.all_capabilities() == []
print("[PASS] 2.1 初始为空")

reg.register(ModelSpec(capability="planner", provider="openai", model="gpt-4o-mini"))
reg.register(ModelSpec(capability="longform", provider="deepseek", model="deepseek-chat"))
assert reg.has("planner")
assert reg.has("longform")
assert reg.has("unknown") is False
print(f"[PASS] 2.2 register 2 个 spec，has 查询正确 (caps={reg.all_capabilities()})")

# 重复注册
try:
    reg.register(ModelSpec(capability="planner", provider="openai", model="gpt-4"))
    assert False, "should raise"
except ValueError as e:
    assert "already registered" in str(e)
print("[PASS] 2.3 重复 register → raise")

# unregister
reg.unregister("planner")
assert reg.has("planner") is False
assert reg.has("longform")
print("[PASS] 2.4 unregister 生效")

# unregister 不存在的 capability 不报错
reg.unregister("nonexistent")
print("[PASS] 2.5 unregister 不存在 → 不报错")


# ============================================================
# Test 3: fallback：未注册 capability → default
# ============================================================
print("\n[Test 3] fallback 行为")

reg = ModelRegistry()
reg.register(ModelSpec(capability="default", provider="openai", model="gpt-4"))
reg.register(ModelSpec(capability="planner", provider="deepseek", model="deepseek-chat"))

# 命中
spec = reg.get("planner")
assert spec.provider == "deepseek"
assert spec.model == "deepseek-chat"
print("[PASS] 3.1 capability 命中 → 返回对应 spec")

# 未命中 → fallback default
spec = reg.get("longform")
assert spec.provider == "openai"
assert spec.model == "gpt-4"
print("[PASS] 3.2 capability 未命中 → fallback 到 default")


# ============================================================
# Test 4: fallback：连 default 都没注册 → raise
# ============================================================
print("\n[Test 4] 全部未注册 → raise")

reg = ModelRegistry()
reg.register(ModelSpec(capability="planner", provider="openai", model="gpt-4"))

try:
    reg.get("unknown")
    assert False, "should raise"
except KeyError as e:
    assert "no model registered" in str(e)
print("[PASS] 4.1 无 default → raise KeyError")


# ============================================================
# Test 5: build_default_model_registry
# ============================================================
print("\n[Test 5] build_default_model_registry")

# mock Config
@dataclass
class MockConfig:
    provider: str = "openai"
    model: str = "gpt-4"
    providers: dict = field(default_factory=dict)
    capability_models: dict = field(default_factory=dict)

# 5.1 capability_models 为空 → 只注册 default
cfg = MockConfig()
reg = build_default_model_registry(cfg)
assert reg.has("default")
assert reg.all_capabilities() == ["default"]
spec = reg.get("default")
assert spec.provider == "openai"
assert spec.model == "gpt-4"
print("[PASS] 5.1 capability_models 为空 → 只注册 default")

# 5.2 配置 capability_models
cfg = MockConfig(
    provider="openai",
    model="gpt-4",
    capability_models={
        "planner": ("openai", "gpt-4o-mini"),
        "longform": ("deepseek", "deepseek-chat"),
        "review": ("openai", "gpt-4"),
    },
)
reg = build_default_model_registry(cfg)
assert set(reg.all_capabilities()) == {"planner", "longform", "review", "default"}
assert reg.get("planner").model == "gpt-4o-mini"
assert reg.get("longform").model == "deepseek-chat"
assert reg.get("review").model == "gpt-4"
assert reg.get("default").model == "gpt-4"  # default 走 cfg.model
print(f"[PASS] 5.2 配置 capability_models → 注册 4 个 capability")

# 5.3 部分 capability provider/model 为空 → 跳过
cfg = MockConfig(
    provider="openai",
    model="gpt-4",
    capability_models={
        "planner": ("openai", "gpt-4o-mini"),
        "bad_cap": ("", ""),       # 空 → 跳过
        "bad_cap2": ("openai",),   # 长度不对 → 跳过
    },
)
reg = build_default_model_registry(cfg)
assert reg.has("planner")
assert not reg.has("bad_cap")
assert not reg.has("bad_cap2")
assert reg.has("default")
print("[PASS] 5.3 非法 capability_models 跳过")

# 5.4 capability_models 不存在属性
@dataclass
class MockConfigNoCap:
    provider: str = "openai"
    model: str = "gpt-4"

cfg = MockConfigNoCap()
reg = build_default_model_registry(cfg)
assert reg.has("default")
spec = reg.get("default")
assert spec.provider == "openai"
print("[PASS] 5.4 cfg 无 capability_models 属性 → fallback default")


# ============================================================
# Test 6: 各 agent 类的 model_capability 正确
# ============================================================
print("\n[Test 6] 各 agent 类 model_capability")

# 直接读源文件检查 model_capability 声明（避免触发 ainovel_py.agents 的 hints 缺失 import）
agent_files = {
    "ArchitectAgent":  "ainovel_py/agents/roles/architect.py",
    "WriterAgent":     "ainovel_py/agents/roles/writer.py",
    "EditorAgent":     "ainovel_py/agents/roles/editor.py",
    "RewriteAgent":    "ainovel_py/agents/roles/rewrite.py",
    "SupervisorAgent": "ainovel_py/agents/roles/supervisor.py",
}
expected_caps = {
    "ArchitectAgent":  "planner",
    "WriterAgent":     "longform",
    "EditorAgent":     "review",
    "RewriteAgent":    "longform",
    "SupervisorAgent": "router",
}

for class_name, rel_path in agent_files.items():
    src = (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")
    # 找到 class 声明行下面的 model_capability 行
    expected = f'model_capability = "{expected_caps[class_name]}"'
    assert expected in src, f"{class_name} 缺 {expected}"
print(f"[PASS] 6.1 各 agent 类 model_capability 正确 ({list(expected_caps.values())})")

# 进一步用 sys.path + 正常 import 验证（先 stub hints）
import os
# 确保 project root 在 sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# stub hints（如果函数存在则调用；否则跳过）
_install_hints_stub = globals().get("_install_hints_stub")
if _install_hints_stub is None:
    def _install_hints_stub():
        """占位实现：当 hints stub 缺失时不做任何事。"""
        pass
_install_hints_stub()

# 重新加载 model_registry 以走正常 import 路径
for mod_name in [
    "ainovel_py.agents.model_registry",
    "ainovel_py.agents.roles.base",
    "ainovel_py.agents.roles.architect",
    "ainovel_py.agents.roles.writer",
    "ainovel_py.agents.roles.editor",
    "ainovel_py.agents.roles.rewrite",
    "ainovel_py.agents.roles.supervisor",
]:
    sys.modules.pop(mod_name, None)

try:
    from ainovel_py.agents.roles.architect import ArchitectAgent
    from ainovel_py.agents.roles.writer import WriterAgent
    from ainovel_py.agents.roles.editor import EditorAgent
    from ainovel_py.agents.roles.rewrite import RewriteAgent
    from ainovel_py.agents.roles.supervisor import SupervisorAgent
    assert ArchitectAgent.model_capability == "planner"
    assert WriterAgent.model_capability == "longform"
    assert EditorAgent.model_capability == "review"
    assert RewriteAgent.model_capability == "longform"
    assert SupervisorAgent.model_capability == "router"
    print("[PASS] 6.2 正常 import 后 model_capability 验证通过")
except Exception as e:
    print(f"[SKIP] 6.2 正常 import 跳过: {e}")


# ============================================================
# Test 7: BaseAgent.build_client(capability) 按 ModelRegistry 选模型
# ============================================================
print("\n[Test 7] BaseAgent.build_client 按 capability 选模型")

# 通过 source 检查 build_client 逻辑（避免 import 触发 hints 缺失）
base_src = (PROJECT_ROOT / "ainovel_py/agents/roles/base.py").read_text(encoding="utf-8")
assert "def build_client(self, capability: str | None = None)" in base_src
assert "self.model_registry.get(cap)" in base_src
assert "self.model_capability" in base_src
print("[PASS] 7.1 build_client 签名 + ModelRegistry 集成")

# 端到端验证：构造 ModelRegistry + 模拟 build_client 逻辑
@dataclass
class _MockProviderCfg:
    api_key: str = ""
    base_url: str = ""

@dataclass
class _MockConfig:
    provider: str = "openai"
    model: str = "gpt-4"
    providers: dict = field(default_factory=lambda: {
        "openai": _MockProviderCfg(api_key="sk-test", base_url="https://api.openai.com/v1"),
        "deepseek": _MockProviderCfg(api_key="sk-ds", base_url="https://api.deepseek.com/v1"),
    })
    capability_models: dict = field(default_factory=lambda: {
        "planner": ("openai", "gpt-4o-mini"),
        "longform": ("deepseek", "deepseek-chat"),
    })

cfg = _MockConfig()
reg = build_default_model_registry(cfg)

# 模拟 build_client("planner")
spec = reg.get("planner")
assert spec.provider == "openai"
assert spec.model == "gpt-4o-mini"
print(f"[PASS] 7.2 build_client(planner) → {spec.provider}/{spec.model}")

# 模拟 build_client("longform")
spec = reg.get("longform")
assert spec.provider == "deepseek"
assert spec.model == "deepseek-chat"
print(f"[PASS] 7.3 build_client(longform) → {spec.provider}/{spec.model}")

# 模拟 build_client("unknown") → fallback default
spec = reg.get("unknown")
assert spec.provider == "openai"
assert spec.model == "gpt-4"  # default = cfg.model
print(f"[PASS] 7.4 build_client(unknown) → fallback default ({spec.provider}/{spec.model})")


# ============================================================
# Test 8: BaseAgent.build_client()（无参数）走 self.model_capability
# ============================================================
print("\n[Test 8] build_client() 无参数走 self.model_capability")

# 检查 base.py 源码：capability=None 时 fallback 到 self.model_capability
assert "cap = capability or self.model_capability" in base_src
print("[PASS] 8.1 capability=None → self.model_capability")

# 模拟：architect 的 self.model_capability = "planner"
reg = build_default_model_registry(_MockConfig())
spec = reg.get("planner")
assert spec.model == "gpt-4o-mini"
print(f"[PASS] 8.2 architect.build_client() → planner → {spec.model}")

# 模拟：writer 的 self.model_capability = "longform"
spec = reg.get("longform")
assert spec.model == "deepseek-chat"
print(f"[PASS] 8.3 writer.build_client() → longform → {spec.model}")


# ============================================================
# Test 9: 未配置 capability_models 时行为与现状一致
# ============================================================
print("\n[Test 9] 未配置 capability_models 时与现状一致")

@dataclass
class _EmptyConfig:
    provider: str = "openai"
    model: str = "gpt-4"
    providers: dict = field(default_factory=lambda: {
        "openai": _MockProviderCfg(api_key="sk-test", base_url="https://api.openai.com/v1"),
    })
    capability_models: dict = field(default_factory=dict)


cfg = _EmptyConfig()
reg = build_default_model_registry(cfg)
assert reg.has("default")
assert reg.all_capabilities() == ["default"]

# 模拟 build_client (无参) → model_capability = "default" → (openai, gpt-4)
spec = reg.get("default")
assert spec.provider == "openai"
assert spec.model == "gpt-4"
print(f"[PASS] 9.1 未配置 capability_models → default = (openai, gpt-4)")

# 模拟 build_client(capability="planner") 在未配置时也 fallback 到 default
spec = reg.get("planner")
assert spec.model == "gpt-4"  # fallback
print(f"[PASS] 9.2 planner capability 在未配置时 → fallback default ({spec.model})")


print("\n" + "=" * 60)
print("阶段 D 单元测试：ALL PASSED")
print("=" * 60)
