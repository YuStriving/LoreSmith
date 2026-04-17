from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_ASSET_ROOT = Path(__file__).resolve().parent


@dataclass
class AssetBundle:
    prompts: dict[str, str] = field(default_factory=dict)
    references: dict[str, str] = field(default_factory=dict)
    styles: dict[str, str] = field(default_factory=dict)


def _read(rel: str) -> str:
    path = _ASSET_ROOT / rel
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_bundle(style: str = "default") -> AssetBundle:
    refs = {
        "outline_template": _read("references/outline-template.md"),
        "character_template": _read("references/character-template.md"),
        "longform_planning": _read("references/longform-planning.md"),
        "differentiation": _read("references/differentiation.md"),
        "consistency": _read("references/consistency.md"),
        "hook_techniques": _read("references/hook-techniques.md"),
        "quality_checklist": _read("references/quality-checklist.md"),
        "chapter_guide": _read("references/chapter-guide.md"),
        "chapter_template": _read("references/chapter-template.md"),
        "content_expansion": _read("references/content-expansion.md"),
        "dialogue_writing": _read("references/dialogue-writing.md"),
    }
    prompts = {
        "coordinator": _read("prompts/coordinator.md"),
        "writer": _read("prompts/writer.md"),
        "editor": _read("prompts/editor.md"),
        "architect_short": _read("prompts/architect-short.md"),
        "architect_mid": _read("prompts/architect-mid.md"),
        "architect_long": _read("prompts/architect-long.md"),
    }
    styles = {
        "default": _read("styles/default.md"),
        style: _read(f"styles/{style}.md") if style else "",
    }
    return AssetBundle(prompts=prompts, references=refs, styles=styles)


def style_text(style: str) -> str:
    text = _read(f"styles/{style}.md") if style else ""
    return text or _read("styles/default.md")


def select_architect_prompt(bundle: AssetBundle, tier: str) -> str:
    tier = (tier or "mid").strip().lower()
    if tier == "short":
        return bundle.prompts.get("architect_short", "")
    if tier == "long":
        return bundle.prompts.get("architect_long", "")
    return bundle.prompts.get("architect_mid", "")


def writer_references(bundle: AssetBundle, chapter: int) -> dict[str, str]:
    refs = {
        "consistency": bundle.references.get("consistency", ""),
        "hook_techniques": bundle.references.get("hook_techniques", ""),
        "quality_checklist": bundle.references.get("quality_checklist", ""),
    }
    if chapter <= 3:
        refs.update(
            {
                "chapter_guide": bundle.references.get("chapter_guide", ""),
                "dialogue_writing": bundle.references.get("dialogue_writing", ""),
            }
        )
    if chapter <= 1:
        refs.update(
            {
                "chapter_template": bundle.references.get("chapter_template", ""),
                "content_expansion": bundle.references.get("content_expansion", ""),
            }
        )
    return {k: v for k, v in refs.items() if v}


def architect_references(bundle: AssetBundle) -> dict[str, str]:
    refs = {
        "outline_template": bundle.references.get("outline_template", ""),
        "character_template": bundle.references.get("character_template", ""),
        "longform_planning": bundle.references.get("longform_planning", ""),
        "differentiation": bundle.references.get("differentiation", ""),
    }
    return {k: v for k, v in refs.items() if v}
