from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from ainovel_py.domain.runtime import RunMeta, SteerEntry, normalize_planning_tier
from ainovel_py.store.io import IO


class RunMetaStore:
    def __init__(self, io: IO) -> None:
        self.io = io

    def load(self) -> RunMeta | None:
        try:
            data = self.io.read_json("meta/run.json")
        except FileNotFoundError:
            return None
        history = [
            SteerEntry(input=str(x.get("input", "") or ""), timestamp=str(x.get("timestamp", "") or ""))
            for x in (data.get("steer_history") or [])
            if isinstance(x, dict)
        ]
        return RunMeta(
            started_at=str(data.get("started_at", "") or ""),
            provider=str(data.get("provider", "") or ""),
            style=str(data.get("style", "") or ""),
            model=str(data.get("model", "") or ""),
            planning_tier=str(data.get("planning_tier", "") or ""),
            steer_history=history,
            pending_steer=str(data.get("pending_steer", "") or ""),
        )

    def save(self, meta: RunMeta) -> None:
        self.io.write_json("meta/run.json", asdict(meta))

    def init(self, style: str, provider: str, model: str) -> None:
        existing = self.load()
        meta = RunMeta(
            started_at=datetime.now(timezone.utc).isoformat(),
            provider=provider,
            style=style,
            model=model,
        )
        if existing:
            meta.steer_history = existing.steer_history
            meta.pending_steer = existing.pending_steer
            meta.planning_tier = existing.planning_tier
        self.save(meta)

    def set_pending_steer(self, text: str) -> None:
        meta = self.load() or RunMeta()
        meta.pending_steer = text
        self.save(meta)

    def set_planning_tier(self, tier: str) -> None:
        normalized = normalize_planning_tier(tier)
        if str(tier or "").strip() and not normalized:
            raise ValueError(f"invalid planning_tier: {tier}")

        def _write() -> None:
            meta = self.load() or RunMeta()
            meta.planning_tier = normalized
            self.save(meta)

        self.io.with_write_lock(_write)
