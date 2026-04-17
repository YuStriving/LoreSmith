from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class RuntimeQueuePriority:
    INTERRUPT = "interrupt"
    CONTROL = "control"
    BACKGROUND = "background"


class RuntimeQueueKind:
    UI_EVENT = "ui_event"
    STREAM_DELTA = "stream_delta"
    STREAM_CHUNK = "stream_chunk"
    STREAM_CLEAR = "stream_clear"
    CONTEXT_BOUNDARY = "context_boundary"
    CONTROL = "control"
    EVIDENCE = "evidence"


@dataclass
class RuntimeQueueItem:
    seq: int = 0
    time: datetime = field(default_factory=datetime.utcnow)
    kind: str = RuntimeQueueKind.UI_EVENT
    priority: str = RuntimeQueuePriority.BACKGROUND
    task_id: str = ""
    agent: str = ""
    category: str = ""
    summary: str = ""
    payload: Any = None


@dataclass
class ControlIntent:
    id: str = ""
    kind: str = ""
    priority: str = RuntimeQueuePriority.CONTROL
    summary: str = ""
    message: str = ""
    prompt: str = ""
    task_kind: str = ""
    task_title: str = ""
    task_input: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    payload: dict[str, str] = field(default_factory=dict)
