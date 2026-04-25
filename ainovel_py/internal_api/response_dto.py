from __future__ import annotations

from typing import Generic, Optional, TypeVar

from pydantic import Field

from pydantic import BaseModel

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    code: str
    message: str
    data: T


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: Optional[dict] = None


class HealthPayload(BaseModel):
    status: str
    host: str
    port: int
    run_count: int


class RunPayload(BaseModel):
    run_id: str
    story_id: str
    status: str
    kernel_status: str
    phase: str
    flow: str
    provider: str
    model: str
    current_chapter: int
    completed_count: int
    total_word_count: int
    latest_checkpoint: Optional[dict] = None
    has_last_commit: bool
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    last_error: Optional[dict] = None
    awaiting_confirmation: Optional[dict] = None


class CreateRunPayload(BaseModel):
    accepted: bool
    run_id: str
    status: str
    kernel_status: str
    started_at: Optional[str] = None


class AckPayload(BaseModel):
    run_id: str
    status: str
    kernel_status: Optional[str] = None
    accepted: Optional[bool] = None


class RunListPayload(BaseModel):
    items: list[RunPayload]


class EventItemPayload(BaseModel):
    event_id: str
    seq: int
    run_id: str
    type: str
    category: str
    time: str
    payload: dict


class EventsPagePayload(BaseModel):
    run_id: str
    after_seq: int
    limit: int
    returned_count: int
    total_available: int
    next_after_seq: int
    has_more: bool
    items: list[EventItemPayload]


class ChapterInnerPayload(BaseModel):
    chapter_number: int
    title: str
    status: str
    word_count: int
    content: str
    summary: Optional[dict] = None
    review: Optional[dict] = None


class ChapterPayload(BaseModel):
    run_id: str
    chapter: ChapterInnerPayload


class ArtifactPayload(BaseModel):
    artifact_id: str
    type: str
    name: str
    chapter: Optional[int] = None
    mime_type: str
    uri: str
    created_at: Optional[str] = None


class ArtifactListPayload(BaseModel):
    run_id: str
    items: list[ArtifactPayload]


class WorkspaceReferenceSnapshotPayload(BaseModel):
    premise: str = ""
    outline: list[dict] = Field(default_factory=list)
    characters: list[dict] = Field(default_factory=list)
    world_rules: list[dict] = Field(default_factory=list)
    timeline: list[dict] = Field(default_factory=list)
    relationship_state: list[dict] = Field(default_factory=list)
    foreshadow_ledger: list[dict] = Field(default_factory=list)
