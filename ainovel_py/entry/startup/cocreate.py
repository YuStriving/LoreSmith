from __future__ import annotations

from dataclasses import dataclass, field

from ainovel_py.host.events import build_start_prompt


@dataclass
class CoCreateSession:
    history: list[dict[str, str]] = field(default_factory=list)
    draft_prompt: str = ""
    ready: bool = False
    stream_reply: str = ""

    @classmethod
    def from_initial(cls, initial: str) -> "CoCreateSession":
        session = cls()
        text = initial.strip()
        if text:
            session.history.append({"role": "user", "content": text})
        return session

    def append_user(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.history.append({"role": "user", "content": text})

    def append_assistant(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.history.append({"role": "assistant", "content": text})

    def apply_delta(self, text: str) -> None:
        if not text:
            return
        self.stream_reply += text

    def apply_reply(self, message: str, prompt: str, ready: bool) -> None:
        final_reply = message.strip() or self.stream_reply.strip()
        if final_reply:
            self.append_assistant(final_reply)
        self.stream_reply = ""
        self.draft_prompt = prompt.strip()
        self.ready = ready or bool(self.draft_prompt)

    def can_start(self) -> bool:
        return bool(self.draft_prompt.strip())

    def initial_input(self) -> str:
        if not self.history:
            return ""
        return (self.history[0].get("content") or "").strip()

    def build_start_prompt(self) -> str:
        if self.can_start():
            return build_start_prompt(self.draft_prompt)
        joined = "\n".join(f"{item.get('role', 'user')}: {item.get('content', '')}" for item in self.history)
        return build_start_prompt(joined)
