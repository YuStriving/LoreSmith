from __future__ import annotations

from ainovel_py.bootstrap.config import Config
from ainovel_py.entry.tui.app import AinovelTUI
from ainovel_py.host.host import Host


def run_tui(cfg: Config) -> int:
    host = Host(cfg)
    app = AinovelTUI(host)
    app.run()
    return 0
