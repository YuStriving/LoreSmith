from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, OptionList, RichLog, Static

from ainovel_py.entry.startup import CoCreateSession
from ainovel_py.entry.tui.bridge import BridgeCallbacks, HostBridge
from ainovel_py.entry.tui.commands import COMMANDS, filter_commands, help_lines, parse_slash
from ainovel_py.host.events import StreamChunk, UISnapshot
from ainovel_py.host.host import Host


class HostEventMsg(Message):
    def __init__(self, line: str) -> None:
        self.line = line
        super().__init__()


class HostStreamMsg(Message):
    def __init__(self, chunk: StreamChunk) -> None:
        self.chunk = chunk
        super().__init__()


class HostClearMsg(Message):
    pass


class HostDoneMsg(Message):
    pass


class HostErrorMsg(Message):
    def __init__(self, err: str) -> None:
        self.err = err
        super().__init__()


class HostStateMsg(Message):
    def __init__(self, state: str) -> None:
        self.state = state
        super().__init__()


class HostSnapshotMsg(Message):
    def __init__(self, snapshot: UISnapshot) -> None:
        self.snapshot = snapshot
        super().__init__()


class CoCreateDoneMsg(Message):
    def __init__(self, result: dict) -> None:
        self.result = result
        super().__init__()


class CoCreateDeltaMsg(Message):
    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


class ModelSelectScreen(ModalScreen[tuple[str, str, str] | None]):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, options: list[tuple[str, str, str]], current: tuple[str, str, str]) -> None:
        super().__init__()
        self.options = options
        self.current = current

    def compose(self) -> ComposeResult:
        yield Static("选择模型（Enter 应用，Esc 关闭）")
        yield OptionList(*[f"{role}: {provider}/{model}" for role, provider, model in self.options], id="model_options")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.options[event.option_index])

    def action_dismiss(self) -> None:
        self.dismiss(None)


class ReportScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Close"), ("q", "dismiss", "Close")]

    def __init__(self, lines: list[str]) -> None:
        super().__init__()
        self.lines = lines

    def compose(self) -> ComposeResult:
        yield Static("运行报告（Esc/q 关闭）")
        log = RichLog(wrap=True, markup=False, highlight=False)
        for line in self.lines:
            log.write(line)
        yield log

    def action_dismiss(self) -> None:
        self.dismiss(None)


class CommandPaletteScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self.current = [cmd.usage for cmd in COMMANDS]

    def compose(self) -> ComposeResult:
        yield Input(placeholder="搜索命令，如 help/model/report", id="command_palette_input")
        yield OptionList(*self.current, id="command_palette_options")

    def on_mount(self) -> None:
        self.query_one("#command_palette_input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "command_palette_input":
            return
        commands = filter_commands(event.value)
        options = self.query_one("#command_palette_options", OptionList)
        options.clear_options()
        self.current = [cmd.usage for cmd in commands]
        for item in self.current:
            options.add_option(item)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "command_palette_input":
            return
        commands = filter_commands(event.value)
        if commands:
            self.dismiss(commands[0].usage)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.current[event.option_index])

    def action_dismiss(self) -> None:
        self.dismiss(None)


class StartupModeScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        yield Static("选择启动模式（Enter 应用，Esc 关闭）")
        yield OptionList("quick", "co-create", id="startup_mode_options")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(["quick", "co-create"][event.option_index])

    def action_dismiss(self) -> None:
        self.dismiss(None)


class CoCreateScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self.session: CoCreateSession | None = None

    def compose(self) -> ComposeResult:
        yield Static("共创规划（输入需求，Enter 发送；输入 /start 开始创作）", id="cocreate_status")
        with Horizontal():
            yield RichLog(id="cocreate_log", wrap=True, markup=False, highlight=False)
            yield Static("prompt 预览将在这里显示", id="cocreate_prompt")
        yield Input(placeholder="描述你的故事想法；/start 开始", id="cocreate_input")

    def set_session(self, session: CoCreateSession) -> None:
        self.session = session
        self._rebuild_from_session()

    def append_line(self, role: str, text: str) -> None:
        self.query_one("#cocreate_log", RichLog).write(f"[{role}] {text}")

    def apply_delta(self, text: str) -> None:
        if not text or self.session is None:
            return
        self.session.apply_delta(text)
        self._refresh_prompt()

    def apply_reply(self, reply: str, prompt: str, ready: bool) -> None:
        if self.session is None:
            return
        self.session.apply_reply(reply, prompt, ready)
        self._rebuild_from_session()

    def _rebuild_from_session(self) -> None:
        if self.session is None:
            return
        log = self.query_one("#cocreate_log", RichLog)
        log.clear()
        for item in self.session.history:
            log.write(f"[{item.get('role', 'user')}] {item.get('content', '')}")
        self._refresh_prompt()

    def _refresh_prompt(self) -> None:
        if self.session is None:
            return
        status = "ready" if self.session.ready else "collecting"
        self.query_one("#cocreate_status", Static).update(
            f"共创规划 [{status}]（输入需求继续沟通；/start 开始）"
        )
        preview = self.session.draft_prompt or "尚未生成 prompt。继续补充故事方向、角色、世界观或核心冲突。"
        if self.session.stream_reply:
            preview += "\n\n[assistant streaming]\n" + self.session.stream_reply
        self.query_one("#cocreate_prompt", Static).update("[Prompt 预览]\n" + preview)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text == "/start":
            if self.session is None or not self.session.can_start():
                self.query_one("#cocreate_log", RichLog).write("[system] 尚未 ready，请先补充想法。")
                return
            self.dismiss("__start__")
            return
        self.dismiss(text)

    def action_dismiss(self) -> None:
        self.dismiss(None)


class AinovelTUI(App[None]):
    CSS = """
    Screen { layout: vertical; }
    #status { height: 1; }
    #main { height: 1fr; }
    #state_panel { width: 24%; border: solid $panel; padding: 0 1; }
    #center { width: 48%; }
    #events { height: 45%; border: solid $panel; }
    #stream { height: 55%; border: solid $panel; }
    #detail_panel { width: 28%; border: solid $panel; padding: 0 1; }
    #input { dock: bottom; }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear", "Clear"),
        ("escape", "abort", "Abort"),
        ("ctrl+p", "command_palette", "Palette"),
        ("tab", "startup_mode", "Startup Mode"),
    ]

    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        self.state = "new"
        self.startup_mode = "quick"
        self.snapshot = UISnapshot()
        self.show_thinking = True
        self._stream_pending = ""
        self._thinking_pending = ""
        self.cocreate: CoCreateSession | None = None
        self.cocreate_screen: CoCreateScreen | None = None
        self.bridge = HostBridge(
            host,
            BridgeCallbacks(
                on_event=lambda line: self.call_from_thread(self.post_message, HostEventMsg(line)),
                on_stream=lambda chunk: self.call_from_thread(self.post_message, HostStreamMsg(chunk)),
                on_clear=lambda: self.call_from_thread(self.post_message, HostClearMsg()),
                on_done=lambda: self.call_from_thread(self.post_message, HostDoneMsg()),
                on_error=lambda err: self.call_from_thread(self.post_message, HostErrorMsg(err)),
                on_state=lambda state: self.call_from_thread(self.post_message, HostStateMsg(state)),
                on_snapshot=lambda snapshot: self.call_from_thread(self.post_message, HostSnapshotMsg(snapshot)),
                on_cocreate_delta=lambda text: self.call_from_thread(self.post_message, CoCreateDeltaMsg(text)),
                on_cocreate_done=lambda result: self.call_from_thread(self.post_message, CoCreateDoneMsg(result)),
            ),
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("状态: new", id="status")
        with Horizontal(id="main"):
            yield Static("", id="state_panel")
            with Vertical(id="center"):
                yield RichLog(id="events", wrap=True, markup=False, highlight=False)
                yield RichLog(id="stream", wrap=True, markup=False, highlight=False)
            yield RichLog(id="detail_panel", wrap=True, markup=False, highlight=False)
        with Vertical():
            yield Input(placeholder="输入剧情或 /help", id="input")
            yield Footer()

    def on_mount(self) -> None:
        self.bridge.start()
        self.bridge.enqueue_bootstrap()
        self._update_status()

    def on_unmount(self) -> None:
        self.bridge.shutdown()

    def action_clear(self) -> None:
        self.query_one("#events", RichLog).clear()
        self.query_one("#stream", RichLog).clear()
        self._stream_pending = ""
        self._thinking_pending = ""

    def action_abort(self) -> None:
        if self.state == "running":
            self.bridge.enqueue_abort()

    def action_command_palette(self) -> None:
        def on_close(result: str | None) -> None:
            if not result:
                return
            self._handle_slash(result.lstrip("/"), [])

        self.push_screen(CommandPaletteScreen(), on_close)

    def action_startup_mode(self) -> None:
        def on_close(result: str | None) -> None:
            if result:
                self.startup_mode = result
                self._update_status()
                self._update_panels()

        self.push_screen(StartupModeScreen(), on_close)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return

        parsed = parse_slash(text)
        if parsed is not None:
            self._handle_slash(*parsed)
            return

        if self.state == "new":
            if self.startup_mode == "co-create":
                self._open_cocreate(text)
                return
            self.bridge.enqueue_start(text)
        elif self.state == "running":
            self.bridge.enqueue_steer(text)
        else:
            self.bridge.enqueue_continue(text)

    def _handle_slash(self, name: str, args: list[str]) -> None:
        events = self.query_one("#events", RichLog)
        if name == "help":
            for line in help_lines():
                events.write(line)
            return
        if name == "resume":
            self.bridge.enqueue_resume()
            return
        if name == "abort":
            self.bridge.enqueue_abort()
            return
        if name == "clear":
            self.action_clear()
            return
        if name == "model":
            self._open_model_selector()
            return
        if name == "report":
            self._open_report()
            return
        if name == "thinking":
            self._toggle_thinking(args)
            return
        if name == "quit":
            self.action_quit()
            return
        events.write(f"未知命令: /{name}")

    def on_host_event_msg(self, message: HostEventMsg) -> None:
        self.query_one("#events", RichLog).write(message.line)

    def on_host_stream_msg(self, message: HostStreamMsg) -> None:
        chunk = message.chunk
        stream = self.query_one("#stream", RichLog)
        if chunk.channel == "thinking":
            if not self.show_thinking:
                return
            self._thinking_pending += chunk.delta
            self._flush_stream_pending(stream, thinking=True)
            return
        self._stream_pending += chunk.delta
        self._flush_stream_pending(stream, thinking=False)

    def _toggle_thinking(self, args: list[str]) -> None:
        events = self.query_one("#events", RichLog)
        stream = self.query_one("#stream", RichLog)
        if not args:
            state = "on" if self.show_thinking else "off"
            events.write(f"thinking 显示: {state}（用 /thinking on|off 切换）")
            return
        value = (args[0] or "").strip().lower()
        if value in {"on", "1", "true"}:
            self.show_thinking = True
            if self._thinking_pending:
                stream.write(f"… {self._thinking_pending}")
                self._thinking_pending = ""
            events.write("thinking 显示已开启")
            return
        if value in {"off", "0", "false"}:
            self.show_thinking = False
            self._thinking_pending = ""
            events.write("thinking 显示已关闭")
            return
        events.write("用法: /thinking [on|off]")

    def _flush_stream_pending(self, stream: RichLog, thinking: bool) -> None:
        buf = self._thinking_pending if thinking else self._stream_pending
        while True:
            idx = buf.find("\n")
            if idx < 0:
                break
            line = buf[:idx]
            buf = buf[idx + 1 :]
            if thinking:
                stream.write(f"… {line}")
            else:
                stream.write(line)
        if thinking:
            self._thinking_pending = buf
        else:
            self._stream_pending = buf

    def on_host_clear_msg(self, message: HostClearMsg) -> None:
        stream = self.query_one("#stream", RichLog)
        if self._thinking_pending and self.show_thinking:
            stream.write(f"… {self._thinking_pending}")
        if self._stream_pending:
            stream.write(self._stream_pending)
        self._thinking_pending = ""
        self._stream_pending = ""
        stream.write("\n")

    def on_host_done_msg(self, message: HostDoneMsg) -> None:
        if self.state == "running":
            self.state = "idle"
            self._update_status()

    def on_host_error_msg(self, message: HostErrorMsg) -> None:
        self.query_one("#events", RichLog).write(f"[ERROR] {message.err}")

    def on_host_state_msg(self, message: HostStateMsg) -> None:
        self.state = message.state
        self._update_status()

    def on_host_snapshot_msg(self, message: HostSnapshotMsg) -> None:
        self.snapshot = message.snapshot
        self._update_status()
        self._update_panels()

    def on_cocreate_delta_msg(self, message: CoCreateDeltaMsg) -> None:
        if self.cocreate_screen:
            self.cocreate_screen.apply_delta(message.text)

    def on_cocreate_done_msg(self, message: CoCreateDoneMsg) -> None:
        result = message.result
        reply = str(result.get("message", "") or "")
        prompt = str(result.get("prompt", "") or "")
        ready = bool(result.get("ready", False))
        if self.cocreate_screen:
            self.cocreate_screen.apply_reply(reply, prompt, ready)

    def _update_status(self) -> None:
        status = self.query_one("#status", Static)
        label = self.snapshot.status_label or self.state
        status.update(
            f"状态: {self.state} | {label} | mode={self.startup_mode} | provider={self.snapshot.provider or self.host.cfg.provider} | model={self.snapshot.model_name or self.host.cfg.model} | 输出目录: {self.host.dir()}"
        )

    def _open_cocreate(self, initial: str) -> None:
        self.cocreate = CoCreateSession.from_initial(initial)
        self.cocreate_screen = CoCreateScreen()
        self.cocreate_screen.set_session(self.cocreate)

        def on_close(result: str | None) -> None:
            if result is None:
                self.cocreate = None
                self.cocreate_screen = None
                return
            if result == "__start__":
                prompt = self.cocreate.build_start_prompt() if self.cocreate else initial
                self.cocreate = None
                self.cocreate_screen = None
                self.bridge.enqueue_start(prompt)
                return

            if self.cocreate:
                self.cocreate.append_user(result)
            if self.cocreate_screen:
                self.cocreate_screen.set_session(self.cocreate)
            self.bridge.enqueue_cocreate(list(self.cocreate.history if self.cocreate else []))
            self.push_screen(self.cocreate_screen, on_close)

        self.push_screen(self.cocreate_screen, on_close)
        if initial and self.cocreate:
            self.bridge.enqueue_cocreate(list(self.cocreate.history))

    def _open_model_selector(self) -> None:
        options: list[tuple[str, str, str]] = []
        current_provider, current_model, _ = self.host.current_model_selection("default")
        for provider in self.host.configured_providers():
            for model in self.host.configured_models(provider):
                options.append(("default", provider, model))
        if not options:
            self.query_one("#events", RichLog).write("没有可选模型")
            return

        def on_close(result: tuple[str, str, str] | None) -> None:
            if result is None:
                return
            role, provider, model = result
            self.bridge.enqueue_switch_model(role, provider, model)

        self.push_screen(ModelSelectScreen(options, ("default", current_provider, current_model)), on_close)

    def _open_report(self) -> None:
        report = self.host.report()
        snap = self.snapshot
        lines = [
            "report / overview:",
            *[f"  - {k}: {report.get(k)}" for k in ["provider", "model", "style", "lifecycle", "output_dir"]],
            "",
            "report / runtime:",
            *[f"  - {k}: {report.get(k)}" for k in ["phase", "flow", "current_chapter", "completed_chapters", "total_word_count"]],
            f"  - status_label: {snap.status_label}",
            f"  - pending_rewrites: {snap.pending_rewrites}",
            f"  - rewrite_reason: {snap.rewrite_reason}",
            f"  - pending_steer: {snap.pending_steer}",
            "",
            "report / checkpoint:",
            f"  - latest: {report.get('latest_checkpoint')}",
            f"  - has_last_commit: {report.get('has_last_commit')}",
            "",
            "report / detail:",
            f"  - premise: {snap.premise[:120] if snap.premise else ''}",
            f"  - outline_items: {len(snap.outline)}",
            f"  - characters: {len(snap.characters)}",
            f"  - recent_summaries: {len(snap.recent_summaries)}",
            f"  - last_review: {snap.last_review_summary}",
        ]
        self.push_screen(ReportScreen(lines))

    def _update_panels(self) -> None:
        state_panel = self.query_one("#state_panel", Static)
        detail_panel = self.query_one("#detail_panel", RichLog)

        state_lines = [
            "[状态]",
            f"runtime: {self.snapshot.runtime_state}",
            f"status: {self.snapshot.status_label}",
            f"mode: {self.startup_mode}",
            f"phase: {self.snapshot.phase}",
            f"flow: {self.snapshot.flow}",
            f"chapter: {self.snapshot.current_chapter}/{self.snapshot.total_chapters}",
            f"completed: {self.snapshot.completed_count}",
            f"words: {self.snapshot.total_word_count}",
            f"provider: {self.snapshot.provider}",
            f"model: {self.snapshot.model_name}",
            f"style: {self.snapshot.style}",
            f"backend: {self.snapshot.backend}",
            f"context: {self.snapshot.context_tokens}/{self.snapshot.context_window} ({self.snapshot.context_percent}%)",
        ]
        if self.snapshot.pending_rewrites:
            state_lines.append(f"pending_rewrites: {self.snapshot.pending_rewrites}")
        if self.snapshot.rewrite_reason:
            state_lines.append(f"rewrite_reason: {self.snapshot.rewrite_reason}")
        if self.snapshot.pending_steer:
            state_lines.append(f"pending_steer: {self.snapshot.pending_steer}")
        if self.snapshot.agent_status:
            state_lines.append("")
            state_lines.append("agents:")
            for item in self.snapshot.agent_status:
                state_lines.append(f"- {item}")
        state_panel.update("\n".join(state_lines))

        detail_lines = ["[详情]"]
        if self.snapshot.premise:
            detail_lines.append("premise:")
            detail_lines.append(self.snapshot.premise)
        if self.snapshot.outline:
            detail_lines.append("")
            detail_lines.append("outline:")
            for item in self.snapshot.outline[:5]:
                detail_lines.append(f"- 第{item['chapter']}章 {item['title']}")
        if self.snapshot.characters:
            detail_lines.append("")
            detail_lines.append("characters:")
            for item in self.snapshot.characters[:8]:
                detail_lines.append(f"- {item}")
        if self.snapshot.recent_summaries:
            detail_lines.append("")
            detail_lines.append("recent_summaries:")
            for item in self.snapshot.recent_summaries:
                detail_lines.append(f"- {item}")
        if self.snapshot.last_review_summary:
            detail_lines.append("")
            detail_lines.append(f"last_review: {self.snapshot.last_review_summary}")
        detail_panel.clear()
        for line in detail_lines:
            detail_panel.write(line)
