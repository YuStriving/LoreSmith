from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import TextIO

from ainovel_py.bootstrap.config import Config
from ainovel_py.domain.runtime_events import RuntimeQueueKind
from ainovel_py.host.events import Event, replay_delta_text, replay_stream_chunk
from ainovel_py.host.host import Host


@dataclass
class Options:
    prompt: str = ""
    stdin: TextIO | None = None
    stdout: TextIO | None = None
    stderr: TextIO | None = None


def run_headless(cfg: Config, opts: Options) -> int:
    stdout = opts.stdout or sys.stdout
    stderr = opts.stderr or sys.stderr

    host = Host(cfg)

    prompt = (opts.prompt or "").strip()
    if prompt:
        stderr.write(f"headless 启动: {host.dir()}\n")
        host.start_prepared(prompt)
    else:
        items = host.replay_queue(0)
        round_has_content = replay_queue(items, stdout, stderr)
        label = host.resume()
        if not label:
            raise ValueError(f'headless 模式需要 --prompt，或输出目录 "{host.dir()}" 下已有可恢复会话')
        stderr.write(f"headless 恢复: {host.dir()} ({label})\n")
        asyncio.run(_consume(host, stdout, stderr, round_has_content))
        return 0

    asyncio.run(_consume(host, stdout, stderr, False))
    return 0


async def _consume(host: Host, stdout: TextIO, stderr: TextIO, round_has_content: bool) -> None:
    while True:
        drained = False
        try:
            ev = host.events.get_nowait()
            write_event(stderr, ev)
            drained = True
        except asyncio.QueueEmpty:
            pass

        try:
            _ = host.clear_ch.get_nowait()
            if round_has_content:
                stdout.write("\n\n")
                round_has_content = False
            drained = True
        except asyncio.QueueEmpty:
            pass

        try:
            chunk = host.stream_ch.get_nowait()
            if chunk and chunk.delta:
                if chunk.channel == "thinking":
                    stderr.write(f"[thinking] {chunk.delta}")
                    stderr.flush()
                else:
                    stdout.write(chunk.delta)
                    stdout.flush()
                    round_has_content = True
            drained = True
        except asyncio.QueueEmpty:
            pass

        try:
            _ = host.done_ch.get_nowait()
            await _drain_pending(host, stdout, stderr, round_has_content)
            return
        except asyncio.QueueEmpty:
            pass

        if not drained:
            await asyncio.sleep(0.01)


async def _drain_pending(host: Host, stdout: TextIO, stderr: TextIO, round_has_content: bool) -> None:
    while True:
        progressed = False

        try:
            ev = host.events.get_nowait()
            write_event(stderr, ev)
            progressed = True
        except asyncio.QueueEmpty:
            pass

        try:
            _ = host.clear_ch.get_nowait()
            if round_has_content:
                stdout.write("\n\n")
                round_has_content = False
            progressed = True
        except asyncio.QueueEmpty:
            pass

        try:
            chunk = host.stream_ch.get_nowait()
            if chunk and chunk.delta:
                if chunk.channel == "thinking":
                    stderr.write(f"[thinking] {chunk.delta}")
                    stderr.flush()
                else:
                    stdout.write(chunk.delta)
                    stdout.flush()
                    round_has_content = True
            progressed = True
        except asyncio.QueueEmpty:
            pass

        if not progressed:
            if round_has_content:
                stdout.write("\n")
            stdout.flush()
            stderr.flush()
            return

        await asyncio.sleep(0)


def write_event(w: TextIO, ev: Event) -> None:
    if not ev.summary.strip():
        return
    ts = ev.time.strftime("%H:%M:%S") if isinstance(ev.time, datetime) else "--:--:--"
    w.write(f"[{ts}] [{ev.category}] {ev.summary}\n")


def replay_queue(items: list, stdout: TextIO, stderr: TextIO) -> bool:
    round_has_content = False
    for item in items:
        if item.kind == RuntimeQueueKind.UI_EVENT:
            summary = item.summary.strip()
            if summary:
                ts = item.time.strftime("%H:%M:%S")
                stderr.write(f"[{ts}] [{item.category}] {summary}\n")
        elif item.kind == RuntimeQueueKind.STREAM_CLEAR:
            if round_has_content:
                stdout.write("\n\n")
                round_has_content = False
        elif item.kind == RuntimeQueueKind.STREAM_CHUNK:
            chunk = replay_stream_chunk(item.payload)
            if chunk and chunk.delta:
                if chunk.channel == "thinking":
                    stderr.write(f"[thinking] {chunk.delta}")
                else:
                    stdout.write(chunk.delta)
                    round_has_content = True
        elif item.kind == RuntimeQueueKind.STREAM_DELTA:
            text = replay_delta_text(item.payload)
            if text:
                stdout.write(text)
                round_has_content = True
    return round_has_content
