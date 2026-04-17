from __future__ import annotations

from datetime import datetime, timezone

from ainovel_py.bootstrap.config import Config, ProviderConfig
from ainovel_py.domain.checkpoint import chapter_scope
from ainovel_py.domain.commit import CommitStage, PendingCommit
from ainovel_py.domain.runtime import Phase, Progress
from ainovel_py.host.resume import build_resume_prompt
from ainovel_py.store.store import Store


def main() -> int:
    cfg = Config(
        output_dir="output/novel",
        provider="openai",
        model="gpt-4o-mini",
        providers={"openai": ProviderConfig(api_key="dummy-key")},
        style="default",
        context_window=128000,
    )

    store = Store(cfg.output_dir)
    store.init()

    store.progress.save(
        Progress(
            novel_name="测试小说",
            phase=Phase.WRITING,
            current_chapter=2,
            total_chapters=6,
            completed_chapters=[1],
            total_word_count=1200,
            in_progress_chapter=2,
        )
    )

    now = datetime.now(timezone.utc).isoformat()
    store.signals.save_pending_commit(
        PendingCommit(
            chapter=2,
            stage=CommitStage.STATE_APPLIED,
            summary="中断测试",
            started_at=now,
            updated_at=now,
        )
    )

    store.checkpoints.append(chapter_scope(2), "draft", artifact="drafts/ch02.draft.md")

    prompt, label = build_resume_prompt(store)
    if "提交中途中断" not in prompt:
        raise RuntimeError("resume prompt should mention pending commit")
    if "第 2 章" not in prompt:
        raise RuntimeError("resume prompt should mention chapter number")
    if "提交中断" not in label:
        raise RuntimeError("resume label should indicate commit interruption")

    print("resume_recovery_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
