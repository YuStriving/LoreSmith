from __future__ import annotations

from dataclasses import dataclass


class CommitStage:
    STARTED = "started"
    STATE_APPLIED = "state_applied"
    PROGRESS_MARKED = "progress_marked"
    SIGNAL_SAVED = "signal_saved"


@dataclass
class PendingCommit:
    chapter: int
    stage: str
    summary: str = ""
    hook_type: str = ""
    dominant_strand: str = ""
    result: dict | None = None
    started_at: str = ""
    updated_at: str = ""
