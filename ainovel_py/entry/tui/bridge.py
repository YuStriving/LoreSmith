from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from ainovel_py.domain.runtime_events import RuntimeQueueKind
from ainovel_py.host.events import StreamChunk, UISnapshot, replay_delta_text, replay_stream_chunk
from ainovel_py.host.host import Host


@dataclass
class BridgeCallbacks:
    on_event: Callable[[str], None]
    on_stream: Callable[[StreamChunk], None]
    on_clear: Callable[[], None]
    on_done: Callable[[], None]
    on_error: Callable[[str], None]
    on_state: Callable[[str], None]
    on_snapshot: Callable[[UISnapshot], None]
    on_cocreate_delta: Callable[[str], None]
    on_cocreate_done: Callable[[dict], None]


class HostBridge:
    def __init__(self, host: Host, callbacks: BridgeCallbacks) -> None:
        self.host = host
        self.callbacks = callbacks
        self._cmd_q: queue.Queue[tuple[str, object]] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._action_thread: threading.Thread | None = None
        self._action_mu = threading.Lock()
        self._tick = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._cmd_q.put(("__stop__", ""))
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._action_thread and self._action_thread.is_alive():
            self._action_thread.join(timeout=1.0)

    def enqueue_bootstrap(self) -> None:
        self._cmd_q.put(("bootstrap", ""))

    def enqueue_start(self, prompt: str) -> None:
        self._cmd_q.put(("start", prompt))

    def enqueue_resume(self) -> None:
        self._cmd_q.put(("resume", ""))

    def enqueue_continue(self, text: str) -> None:
        self._cmd_q.put(("continue", text))

    def enqueue_steer(self, text: str) -> None:
        self._cmd_q.put(("steer", text))

    def enqueue_abort(self) -> None:
        self._cmd_q.put(("abort", ""))

    def enqueue_switch_model(self, role: str, provider: str, model: str) -> None:
        self._cmd_q.put(("switch_model", {"role": role, "provider": provider, "model": model}))

    def enqueue_cocreate(self, history: list[dict[str, str]]) -> None:
        self._cmd_q.put(("cocreate", history))

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                cmd, payload = self._cmd_q.get(timeout=0.02)
                if cmd == "__stop__":
                    return
                if cmd in {"start", "resume", "continue"}:
                    self._launch_action(cmd, payload)
                else:
                    self._handle_command(cmd, payload)
            except queue.Empty:
                pass
            except Exception as exc:
                self.callbacks.on_error(f"bridge command error: {exc}")

            self._drain_host_queues()
            self._tick += 1
            if self._tick % 10 == 0:
                try:
                    self.callbacks.on_snapshot(self.host.snapshot())
                except Exception as exc:
                    self.callbacks.on_error(f"snapshot error: {exc}")

    def _launch_action(self, cmd: str, payload: object) -> None:
        with self._action_mu:
            if self._action_thread and self._action_thread.is_alive():
                self.callbacks.on_error("已有任务在执行，请稍候")
                return
            self.callbacks.on_state("running")
            self._action_thread = threading.Thread(target=self._run_action, args=(cmd, payload), daemon=True)
            self._action_thread.start()

    def _run_action(self, cmd: str, payload: object) -> None:
        try:
            if cmd == "start":
                self.host.start_prepared(payload)
            elif cmd == "resume":
                label = self.host.resume()
                if label:
                    self.callbacks.on_event(f"[{datetime.now().strftime('%H:%M:%S')}] [SYSTEM] 恢复标签: {label}")
                else:
                    self.callbacks.on_event(f"[{datetime.now().strftime('%H:%M:%S')}] [SYSTEM] 无可恢复会话")
            elif cmd == "continue":
                self.host.continue_run(payload)
        except Exception as exc:
            self.callbacks.on_error(str(exc))
        finally:
            self.callbacks.on_state("idle")

    def _handle_command(self, cmd: str, payload: object) -> None:
        try:
            if cmd == "bootstrap":
                items = self.host.replay_queue(0)
                for item in items:
                    if item.kind == RuntimeQueueKind.UI_EVENT:
                        ts = item.time.strftime("%H:%M:%S")
                        summary = item.summary.strip()
                        if summary:
                            self.callbacks.on_event(f"[{ts}] [{item.category}] {summary}")
                    elif item.kind == RuntimeQueueKind.STREAM_CLEAR:
                        self.callbacks.on_clear()
                    elif item.kind == RuntimeQueueKind.STREAM_CHUNK:
                        chunk = replay_stream_chunk(item.payload)
                        if chunk:
                            self.callbacks.on_stream(chunk)
                    elif item.kind == RuntimeQueueKind.STREAM_DELTA:
                        text = replay_delta_text(item.payload)
                        if text:
                            self.callbacks.on_stream(StreamChunk(channel="content", delta=text))
                return

            if cmd == "steer":
                self.host.steer(payload)
            elif cmd == "abort":
                self.host.abort()
                self.callbacks.on_state("paused")
            elif cmd == "switch_model":
                if not isinstance(payload, dict):
                    raise ValueError("invalid switch_model payload")
                self.host.switch_model(
                    str(payload.get("role", "default") or "default"),
                    str(payload.get("provider", "") or ""),
                    str(payload.get("model", "") or ""),
                )
                self.callbacks.on_snapshot(self.host.snapshot())
            elif cmd == "cocreate":
                if not isinstance(payload, list):
                    raise ValueError("invalid cocreate payload")
                result = self.host.co_create_reply(payload, on_delta=self.callbacks.on_cocreate_delta)
                self.callbacks.on_cocreate_done(result)
        except Exception as exc:
            self.callbacks.on_error(str(exc))
            self.callbacks.on_state("idle")

    def _drain_host_queues(self) -> None:
        while True:
            progressed = False
            try:
                ev = self.host.events.get_nowait()
                ts = ev.time.strftime("%H:%M:%S")
                self.callbacks.on_event(f"[{ts}] [{ev.category}] {ev.summary}")
                progressed = True
            except Exception:
                pass

            try:
                _ = self.host.clear_ch.get_nowait()
                self.callbacks.on_clear()
                progressed = True
            except Exception:
                pass

            try:
                chunk = self.host.stream_ch.get_nowait()
                if chunk and chunk.delta:
                    self.callbacks.on_stream(chunk)
                progressed = True
            except Exception:
                pass

            try:
                _ = self.host.done_ch.get_nowait()
                self.callbacks.on_done()
                progressed = True
            except Exception:
                pass

            if not progressed:
                return
