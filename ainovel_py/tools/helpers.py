from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any


def dataclass_to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [dataclass_to_dict(v) for v in value]
    if isinstance(value, dict):
        return {k: dataclass_to_dict(v) for k, v in value.items()}
    return value


def parse_json_content(content: Any) -> Any:
    if isinstance(content, str):
        text = content.strip()
        if not text:
            return ""
        try:
            return json.loads(text)
        except Exception:
            return text
    return content
