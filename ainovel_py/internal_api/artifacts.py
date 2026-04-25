from __future__ import annotations

from pathlib import Path

from ainovel_py.store.store import Store


class ArtifactService:
    def list_artifacts(self, output_dir: str, run_id: str) -> list[dict[str, object]]:
        store = Store(output_dir)
        store.init()
        items: list[dict[str, object]] = []
        base = Path(output_dir)

        progress = store.progress.load()
        completed = set(progress.completed_chapters if progress else [])
        for p in (base / "chapters").glob("*.md") if (base / "chapters").exists() else []:
            stem = p.stem.strip()
            if stem.isdigit():
                completed.add(int(stem))
        for p in (base / "summaries").glob("*.json") if (base / "summaries").exists() else []:
            stem = p.stem.strip()
            if stem.isdigit():
                completed.add(int(stem))
        for p in (base / "reviews").glob("*.json") if (base / "reviews").exists() else []:
            stem = p.stem.strip().replace("-global", "")
            if stem.isdigit():
                completed.add(int(stem))

        for chapter in sorted(completed):
            chapter_path = base / "chapters" / f"{chapter:02d}.md"
            if chapter_path.exists():
                items.append({
                    "artifact_id": f"art_{run_id}_chapter_{chapter:02d}",
                    "type": "chapter",
                    "name": f"chapter-{chapter:03d}",
                    "chapter": chapter,
                    "mime_type": "text/markdown",
                    "uri": str(chapter_path),
                    "created_at": chapter_path.stat().st_mtime,
                })
            summary_path = base / "summaries" / f"{chapter:02d}.json"
            if summary_path.exists():
                items.append({
                    "artifact_id": f"art_{run_id}_summary_{chapter:02d}",
                    "type": "summary",
                    "name": f"summary-{chapter:03d}",
                    "chapter": chapter,
                    "mime_type": "application/json",
                    "uri": str(summary_path),
                    "created_at": summary_path.stat().st_mtime,
                })
            review_path = base / "reviews" / f"{chapter:02d}.json"
            if review_path.exists():
                items.append({
                    "artifact_id": f"art_{run_id}_review_{chapter:02d}",
                    "type": "review",
                    "name": f"review-{chapter:03d}",
                    "chapter": chapter,
                    "mime_type": "application/json",
                    "uri": str(review_path),
                    "created_at": review_path.stat().st_mtime,
                })

        premise_path = base / "premise.md"
        if premise_path.exists():
            items.append({
                "artifact_id": f"art_{run_id}_premise",
                "type": "premise",
                "name": "premise",
                "chapter": None,
                "mime_type": "text/markdown",
                "uri": str(premise_path),
                "created_at": premise_path.stat().st_mtime,
            })
        outline_path = base / "outline.json"
        if outline_path.exists():
            items.append({
                "artifact_id": f"art_{run_id}_outline",
                "type": "outline",
                "name": "outline",
                "chapter": None,
                "mime_type": "application/json",
                "uri": str(outline_path),
                "created_at": outline_path.stat().st_mtime,
            })
        return items
