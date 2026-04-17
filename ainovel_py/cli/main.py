from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ainovel_py.bootstrap.configfile import load_config, needs_setup
from ainovel_py.entry.headless.run import Options, run_headless


def _parse_cli_options(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(prog="ainovel-py", add_help=True)
    parser.add_argument("--config", dest="config_path", default="")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--prompt-file", default="")
    opts, args = parser.parse_known_args(argv)

    if opts.prompt and opts.prompt_file:
        raise ValueError("--prompt 和 --prompt-file 不能同时使用")
    return opts, args


def _load_prompt(opts: argparse.Namespace) -> str:
    if not opts.prompt_file:
        return (opts.prompt or "").strip()
    if opts.prompt_file == "-":
        return sys.stdin.read().strip()
    return Path(opts.prompt_file).read_text(encoding="utf-8").strip()


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    try:
        opts, args = _parse_cli_options(argv)
    except Exception as exc:
        sys.stderr.write(f"flags: {exc}\n")
        return 1

    if args:
        sys.stderr.write("error: 不再支持命令行直接传入小说需求，请启动后输入 prompt\n")
        return 1

    if needs_setup(opts.config_path):
        if opts.headless:
            sys.stderr.write("error: headless 模式不支持首次引导，请先准备配置文件\n")
            return 1
        sys.stderr.write("error: 当前 Python 版本暂未实现首次 TUI 引导，请先创建配置文件\n")
        return 1

    try:
        cfg = load_config(opts.config_path)
        cfg.validate_base()
    except Exception as exc:
        sys.stderr.write(f"config: {exc}\n")
        return 1

    if opts.headless:
        try:
            prompt = _load_prompt(opts)
            return run_headless(cfg, Options(prompt=prompt))
        except Exception as exc:
            sys.stderr.write(f"error: {exc}\n")
            return 1

    if opts.prompt or opts.prompt_file:
        sys.stderr.write("error: --prompt/--prompt-file 仅能在 --headless 模式下使用\n")
        return 1

    try:
        from ainovel_py.entry.tui.run import run_tui

        return run_tui(cfg)
    except Exception as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
