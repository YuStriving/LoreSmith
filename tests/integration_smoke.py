from __future__ import annotations

import os

from ainovel_py.bootstrap.config import Config, ProviderConfig
from ainovel_py.bootstrap.configfile import load_config
from ainovel_py.host.host import Host


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required env: {name}")
    return value


def main() -> int:
    if os.environ.get("AINOVEL_LIVE_TEST", "").strip() != "1":
        raise RuntimeError("live LLM test disabled; set AINOVEL_LIVE_TEST=1")

    config_path = os.environ.get("AINOVEL_CONFIG", "").strip()
    if config_path:
        cfg = load_config(config_path)
    else:
        provider = os.environ.get("AINOVEL_PROVIDER", "openrouter").strip() or "openrouter"
        model = _require("AINOVEL_MODEL")
        api_key = _require("AINOVEL_API_KEY")
        base_url = os.environ.get("AINOVEL_BASE_URL", "").strip()
        cfg = Config(
            output_dir="output/novel",
            provider=provider,
            model=model,
            providers={provider: ProviderConfig(api_key=api_key, base_url=base_url)},
            style="default",
            context_window=128000,
        )

    cfg.fill_defaults()
    cfg.validate_base()
    host = Host(cfg)
    host.store.signals.clear_pending_commit()
    host.store.signals.clear_stale_signals()
    host.store.checkpoints.reset()
    host.start_prepared("测试剧情：主角在雨夜觉醒并卷入阴谋。")

    progress = host.store.progress.load()
    if progress is None:
        raise RuntimeError("progress not initialized")
    if not progress.completed_chapters:
        raise RuntimeError("no committed chapter")

    summary = host.store.summaries.load_summary(1)
    if summary is None:
        raise RuntimeError("summary for chapter 1 missing")

    latest = progress.completed_chapters[-1]
    review = host.store.world.load_review(latest)
    if review is None:
        raise RuntimeError(f"review for chapter {latest} missing")

    print("integration_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
