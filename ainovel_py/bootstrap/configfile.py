from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import Config, provider_config_from_dict, role_config_from_dict

CONFIG_DIR_NAME = ".ainovel"


def default_config_path() -> str:
    home = Path.home()
    return str(home / CONFIG_DIR_NAME / "config.json")


def _strip_json_comments(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if escaped:
            out.append(ch)
            escaped = False
            i += 1
            continue
        if in_string:
            out.append(ch)
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            if i < n:
                out.append("\n")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _load_json_file(path: str) -> Config:
    raw = Path(path).read_text(encoding="utf-8")
    cleaned = _strip_json_comments(raw)
    data = json.loads(cleaned)
    return _config_from_dict(data)


def _config_from_dict(data: dict[str, Any]) -> Config:
    providers_raw = data.get("providers", {}) or {}
    roles_raw = data.get("roles", {}) or {}
    providers = {
        str(name): provider_config_from_dict(cfg)
        for name, cfg in providers_raw.items()
        if isinstance(cfg, dict)
    }
    roles = {
        str(name): role_config_from_dict(cfg)
        for name, cfg in roles_raw.items()
        if isinstance(cfg, dict)
    }
    return Config(
        provider=str(data.get("provider", "") or ""),
        model=str(data.get("model", "") or ""),
        providers=providers,
        roles=roles,
        style=str(data.get("style", "") or ""),
        context_window=int(data.get("context_window", 0) or 0),
    )


def _merge_config(base: Config, overlay: Config) -> Config:
    if overlay.provider:
        base.provider = overlay.provider
    if overlay.model:
        base.model = overlay.model
    if overlay.style:
        base.style = overlay.style
    if overlay.context_window > 0:
        base.context_window = overlay.context_window

    for key, value in overlay.providers.items():
        existing = base.providers.get(key)
        if existing is None:
            base.providers[key] = value
            continue
        if value.type:
            existing.type = value.type
        if value.api_key:
            existing.api_key = value.api_key
        if value.base_url:
            existing.base_url = value.base_url
        if value.models:
            existing.models = list(value.models)
        base.providers[key] = existing

    for key, value in overlay.roles.items():
        existing = base.roles.get(key)
        if existing is None:
            base.roles[key] = value
            continue
        if value.provider:
            existing.provider = value.provider
        if value.model:
            existing.model = value.model
        if value.fallbacks:
            existing.fallbacks = list(value.fallbacks)
        base.roles[key] = existing

    return base


def load_config(flag_path: str = "") -> Config:
    cfg = Config()

    global_path = default_config_path()
    if Path(global_path).exists():
        cfg = _load_json_file(global_path)

    project_path = Path("ainovel.json")
    if project_path.exists():
        cfg = _merge_config(cfg, _load_json_file(str(project_path)))

    if flag_path:
        cfg = _merge_config(cfg, _load_json_file(flag_path))

    cfg.fill_defaults()
    return cfg


def needs_setup(flag_path: str = "") -> bool:
    if flag_path:
        return not Path(flag_path).exists()
    if Path(default_config_path()).exists():
        return False
    if Path("ainovel.json").exists():
        return False
    return True


def save_config(path: str, cfg: Config) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "provider": cfg.provider,
        "model": cfg.model,
        "providers": {
            name: {
                "type": pc.type,
                "api_key": pc.api_key,
                "base_url": pc.base_url,
                "models": pc.models,
            }
            for name, pc in cfg.providers.items()
        },
        "roles": {
            name: {
                "provider": rc.provider,
                "model": rc.model,
                "fallbacks": [
                    {"provider": fb.provider, "model": fb.model} for fb in rc.fallbacks
                ],
            }
            for name, rc in cfg.roles.items()
        },
        "style": cfg.style,
        "context_window": cfg.context_window,
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
