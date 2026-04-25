from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RunTask:
    task_id: str
    run_id: str
    op: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    created_at: datetime = field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str = ""
