from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from metadata_parser import normalize_name


class ReferenceRuleLibrary:
    def __init__(self, json_path: str | Path | None = None) -> None:
        path = Path(json_path) if json_path else Path(__file__).with_name("reference_mapping_rules.json")
        self._rules: dict[tuple[str, str], dict[str, Any]] = {}
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            for rule in payload.get("rules", []):
                key = (
                    rule.get("normalized_target_object") or normalize_name(rule.get("target_object")),
                    rule.get("normalized_target_column") or normalize_name(rule.get("target_column")),
                )
                self._rules[key] = rule

    def find(self, target_object: str, target_column: str) -> dict[str, Any] | None:
        return self._rules.get((normalize_name(target_object), normalize_name(target_column)))
