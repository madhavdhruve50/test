from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from metadata_parser import normalize_name


@dataclass
class FormulaLineage:
    target_object: str
    target_column: str
    formula: str
    source_objects: list[str]
    source_columns: list[str]
    notes: str


def normalize_formula(formula: str) -> str:
    formula = formula.replace("FORMULA_TEXT:", "").strip()
    formula = re.sub(r"\$", "", formula)
    formula = re.sub(r"(?<=[A-Z])\d+", "#", formula)
    formula = re.sub(r"\b\d+\b", "#", formula)
    formula = re.sub(r"\s+", "", formula)
    return formula.lower()


def _strip_prefix(formula: str) -> str:
    formula = formula.replace("FORMULA_TEXT:", "").strip()
    return formula[1:].strip() if formula.startswith("=") else formula


def _source_objects(formula: str, target_object: str) -> list[str]:
    objects: list[str] = []
    # External workbook and sheet references: '[Book.xlsx]Sheet'!
    for book, sheet in re.findall(r"'\[([^\]]+)\]([^']+)'!", formula):
        value = f"{book} / {sheet}"
        if value not in objects:
            objects.append(value)
    # Quoted and unquoted sheet references.
    for quoted, plain in re.findall(r"(?:'([^']+)'|([A-Za-z0-9_ -]+))!", formula):
        value = (quoted or plain).strip()
        if value and value not in objects:
            objects.append(value)
    # Readable metadata often uses Sheet.Column notation.
    for sheet in re.findall(r"\b([A-Za-z][A-Za-z0-9_ -]{1,50})\.[A-Za-z_][A-Za-z0-9_ #/-]*", formula):
        sheet = sheet.strip()
        if sheet and sheet not in objects:
            objects.append(sheet)
    if not objects:
        objects.append(target_object)
    return objects


def _source_columns(formula: str) -> list[str]:
    columns: list[str] = []
    patterns = [
        r"\[@\[([^\]]+)\]\]",
        r"\[\[?([A-Za-z_][A-Za-z0-9_ #/()-]+)\]?\]",
        r"\b[A-Za-z][A-Za-z0-9_ -]{1,50}\.([A-Za-z_][A-Za-z0-9_ #/()-]+)",
    ]
    for pattern in patterns:
        for value in re.findall(pattern, formula):
            value = value.strip().rstrip(")")
            if value and normalize_name(value) not in {"formula text", "row"} and value not in columns:
                columns.append(value)
    return columns[:20]


def parse_formula_rows(rows: Iterable[dict[str, str]]) -> list[FormulaLineage]:
    output: list[FormulaLineage] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        target_object = row["target_object"].strip()
        target_column = row["target_column"].strip()
        formula = row.get("readable_formula") or row.get("original_formula") or ""
        key = (normalize_name(target_object), normalize_name(target_column), normalize_formula(formula))
        if not target_object or not target_column or not formula or key in seen:
            continue
        seen.add(key)
        stripped = _strip_prefix(formula)
        output.append(
            FormulaLineage(
                target_object=target_object,
                target_column=target_column,
                formula=stripped,
                source_objects=_source_objects(stripped, target_object),
                source_columns=_source_columns(stripped),
                notes="Formula-derived mapping from Formulas_Sample; repeated row formulas were deduplicated.",
            )
        )
    return output


def index_formulas(formulas: Iterable[FormulaLineage]) -> dict[tuple[str, str], FormulaLineage]:
    return {
        (normalize_name(item.target_object), normalize_name(item.target_column)): item
        for item in formulas
    }
