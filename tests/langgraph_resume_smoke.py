from __future__ import annotations

import shutil
from pathlib import Path

from ainovel_py.agents.build import build_tool_registry
from ainovel_py.agents.orchestrator.langgraph.core import LangGraphRuntime
from ainovel_py.bootstrap.config import Config, ProviderConfig
from ainovel_py.domain.checkpoint import chapter_scope
from ainovel_py.domain.commit import CommitStage, PendingCommit
from ainovel_py.domain.runtime import Phase, Progress
from ainovel_py.domain.story import OutlineEntry
from ainovel_py.store.store import Store


TEST_DIR = Path("output/langgraph_resume_smoke")


class _StubClient:
    def complete(self, system_prompt, user_prompt, temperature=0.0):
        return '{"summary":"第2章恢复总结","characters":["主角"],"key_events":["恢复提交"],"timeline_events":[],"foreshadow_updates":[],"relationship_changes":[],"state_changes":[],"hook_type":"mystery","dominant_strand":"quest"}'


class StubLangGraphRuntime(LangGraphRuntime):
    def build_client(self):
        return _StubClient()

    def _generate_chapter_with_context(self, client, seed_text, chapter, context, plan, contract):
        return (f"第{chapter}章恢复后的正文。", 12)

    def _summarize_chapter(self, client, chapter, draft):
        return f"第{chapter}章恢复总结"


def _setup_store() -> Store:
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    store = Store(str(TEST_DIR))
    store.init()
    store.progress.save(
        Progress(
            novel_name="恢复测试小说",
            phase=Phase.WRITING,
            current_chapter=2,
            total_chapters=2,
            completed_chapters=[1],
            total_word_count=100,
            in_progress_chapter=2,
        )
    )
    store.outline.save_premise("# 恢复测试小说\n一个恢复场景。")
    store.outline.save_outline([
        OutlineEntry(chapter=1, title="第一章", core_event="开始", hook="继续", scenes=["场景1"]),
        OutlineEntry(chapter=2, title="第二章", core_event="恢复提交", hook="完成", scenes=["场景2"]),
    ])
    store.drafts.save_draft(2, "第2章草稿，等待提交。")
    store.checkpoints.append(chapter_scope(2), "draft", artifact="drafts/ch02.draft.md")
    store.signals.save_pending_commit(
        PendingCommit(
            chapter=2,
            stage=CommitStage.STATE_APPLIED,
            summary="恢复测试",
            started_at="2026-04-17T00:00:00+00:00",
            updated_at="2026-04-17T00:00:00+00:00",
        )
    )
    return store


def main() -> int:
    store = _setup_store()
    cfg = Config(
        output_dir=str(TEST_DIR),
        provider="openai",
        model="gpt-4o-mini",
        providers={"openai": ProviderConfig(api_key="test-key")},
        style="default",
        context_window=128000,
    )
    runner = type("Runner", (), {"call_tool": lambda self, name, args: build_tool_registry(store)[name].execute(args)})()
    runtime = StubLangGraphRuntime(cfg, runner, store, lambda event: None, lambda channel, delta: None)
    runtime.resume("恢复执行")

    progress = store.progress.load()
    if progress is None or 2 not in progress.completed_chapters:
        raise RuntimeError("resume did not commit chapter 2")
    if store.signals.load_pending_commit() is not None:
        raise RuntimeError("pending commit should be cleared after resume")
    checkpoint = store.checkpoints.latest(chapter_scope(2))
    if checkpoint is None or checkpoint.step != "commit":
        raise RuntimeError("resume commit checkpoint missing")

    print("langgraph_resume_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
