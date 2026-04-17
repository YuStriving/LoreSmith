from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    name: str
    usage: str
    description: str


COMMANDS = [
    CommandSpec("help", "/help", "显示帮助"),
    CommandSpec("resume", "/resume", "尝试恢复会话"),
    CommandSpec("abort", "/abort", "暂停当前执行"),
    CommandSpec("clear", "/clear", "清空界面日志"),
    CommandSpec("model", "/model", "打开模型选择面板"),
    CommandSpec("report", "/report", "打开运行报告面板"),
    CommandSpec("thinking", "/thinking [on|off]", "切换思考流显示"),
    CommandSpec("quit", "/quit", "退出 TUI"),
]


def parse_slash(text: str) -> tuple[str, list[str]] | None:
    raw = text.strip()
    if not raw.startswith("/"):
        return None
    body = raw[1:].strip()
    if not body:
        return "", []
    parts = body.split()
    return parts[0].lower(), parts[1:]


def help_lines() -> list[str]:
    return [f"{cmd.usage} - {cmd.description}" for cmd in COMMANDS]


def filter_commands(query: str) -> list[CommandSpec]:
    q = query.strip().lower().lstrip("/")
    if not q:
        return list(COMMANDS)
    exact = [cmd for cmd in COMMANDS if cmd.name == q]
    prefix = [cmd for cmd in COMMANDS if cmd.name.startswith(q) and cmd not in exact]
    contains = [cmd for cmd in COMMANDS if q in cmd.name and cmd not in exact and cmd not in prefix]
    return exact + prefix + contains
