from __future__ import annotations

import shutil
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ainovel_py.domain.runtime import Phase, Progress
from ainovel_py.domain.writing import ChapterSummary
from ainovel_py.internal_api.app import create_app
from ainovel_py.internal_api.workspace_dto import WorkspaceIntentRequest
from ainovel_py.store.store import Store


def main() -> int:
    workspace_path = ROOT / "output" / "workspace" / "story_workspace"
    shutil.rmtree(workspace_path, ignore_errors=True)
    try:
        store = Store(str(workspace_path))
        store.init()
        store.progress.save(Progress(novel_name="标题", phase=Phase.WRITING, completed_chapters=[1], current_chapter=2))
        store.summaries.save_summary(ChapterSummary(chapter=1, summary="第一章摘要", characters=["主角"], key_events=["事件1"]))

        app = create_app()
        client = TestClient(app)

        plan = client.post(
            "/internal/v1/workspace/intent",
            json={
                "intent_type": "chapter_plan",
                "story": {"story_id": "story_workspace", "title": "标题", "premise": "设定", "style": "default"},
                "node": {"node_id": "chapter-2", "type": "chapter", "title": "第二章", "summary": "摘要"},
                "payload": {"title": "第二章", "goal": "推进冲突", "conflict": "门外有人", "hook": "灯灭了"},
            },
        )
        if plan.status_code != 200:
            raise RuntimeError(f"chapter plan failed: {plan.status_code} {plan.text}")
        if plan.json()["data"]["result"].get("asset_type") != "plan":
            raise RuntimeError(f"unexpected chapter plan response: {plan.text}")

        draft = client.post(
            "/internal/v1/workspace/intent",
            json={
                "intent_type": "chapter_draft",
                "story": {"story_id": "story_workspace", "title": "标题", "premise": "设定", "style": "default"},
                "node": {"node_id": "chapter-2", "type": "chapter", "title": "第二章", "summary": "摘要"},
                "content": "第二章草稿正文。",
            },
        )
        if draft.status_code != 200:
            raise RuntimeError(f"chapter draft failed: {draft.status_code} {draft.text}")
        if draft.json()["data"]["result"].get("asset_type") != "draft":
            raise RuntimeError(f"unexpected chapter draft response: {draft.text}")

        read_draft = client.post(
            "/internal/v1/workspace/intent",
            json={
                "intent_type": "chapter_read_asset",
                "story": {"story_id": "story_workspace", "title": "标题", "premise": "设定", "style": "default"},
                "node": {"node_id": "chapter-2", "type": "chapter", "title": "第二章", "summary": "摘要", "asset_type": "draft"},
            },
        )
        if read_draft.status_code != 200:
            raise RuntimeError(f"chapter read failed: {read_draft.status_code} {read_draft.text}")
        if read_draft.json()["data"]["result"].get("content") != "第二章草稿正文。":
            raise RuntimeError(f"unexpected chapter read response: {read_draft.text}")

        commit = client.post(
            "/internal/v1/workspace/intent",
            json={
                "intent_type": "chapter_commit",
                "story": {"story_id": "story_workspace", "title": "标题", "premise": "设定", "style": "default"},
                "node": {"node_id": "chapter-2", "type": "chapter", "title": "第二章", "summary": "摘要"},
                "payload": {
                    "summary": "第二章摘要",
                    "characters": ["主角"],
                    "key_events": ["事件2"],
                    "timeline_events": [{"time": "深夜", "event": "听见脚步", "characters": ["主角"]}],
                },
            },
        )
        if commit.status_code != 200:
            raise RuntimeError(f"chapter commit failed: {commit.status_code} {commit.text}")
        commit_data = commit.json()["data"]["result"]
        if commit_data.get("asset_type") != "chapter":
            raise RuntimeError(f"unexpected chapter commit response: {commit.text}")
        saved_summary = Store(str(workspace_path)).summaries.load_summary(2)
        if saved_summary is None or saved_summary.summary != "第二章摘要":
            raise RuntimeError(f"summary asset not saved correctly: {saved_summary}")

        workspace_context = client.app.state.workspace_service._workspace_context(
            WorkspaceIntentRequest(
                intent_type="assistant_reply",
                story={"story_id": "story_workspace", "title": "标题", "premise": "设定", "style": "default"},
                node={"node_id": "chapter-2", "type": "chapter", "title": "第二章", "summary": "摘要"},
                instruction="继续写第二章",
            ),
            style="default",
        )
        if workspace_context.get("recent_summaries", [{}])[0].get("summary") != "第一章摘要":
            raise RuntimeError(f"unexpected workspace store context: {workspace_context}")

        consistency = client.post(
            "/internal/v1/workspace/intent",
            json={
                "intent_type": "consistency_scan",
                "story": {"story_id": "story_workspace", "title": "标题", "premise": "设定", "style": "default"},
                "node": {"node_id": "chapter-1", "type": "chapter", "title": "第一章", "summary": "摘要"},
                "content": "TODO 第二天发生在第一天之前",
            },
        )
        if consistency.status_code != 200:
            raise RuntimeError(f"consistency intent failed: {consistency.status_code} {consistency.text}")
        issues = consistency.json()["data"]["result"].get("issues", [])
        if len(issues) < 2:
            raise RuntimeError(f"unexpected consistency issues: {consistency.text}")

        run_route = client.post(
            "/internal/v1/workspace/intent",
            json={
                "intent_type": "run_continue",
                "story": {"story_id": "story_workspace", "title": "标题", "premise": "设定", "style": "default"},
                "node": {"node_id": "chapter-1", "type": "chapter", "title": "第一章", "summary": "摘要"},
                "instruction": "继续推进",
            },
        )
        if run_route.status_code != 200:
            raise RuntimeError(f"run route intent failed: {run_route.status_code} {run_route.text}")
        if run_route.json()["data"]["route"] != "run_agent":
            raise RuntimeError(f"unexpected run route response: {run_route.text}")

        print("internal_api_workspace_intent_smoke: ok")
        return 0
    finally:
        shutil.rmtree(workspace_path, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
