from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import pandas as pd

from config import OUTPUT_COLUMNS
from coverage_validator import CoverageResult, compare_coverage
from excel_writer import build_output_excel
from formula_parser import FormulaLineage, index_formulas, parse_formula_rows
from metadata_parser import (
    MetadataWorkbook,
    build_header_catalog,
    build_query_target_map,
    clean_text,
    get_formula_rows,
    get_power_query_rows,
    normalize_name,
    parse_metadata_workbook,
)
from reference_rules import ReferenceRuleLibrary
from sql_parser import ParsedQuery, SQLColumnLineage, parse_power_query_sql


@dataclass
class GenerationResult:
    mapping: pd.DataFrame
    coverage: CoverageResult
    excel_bytes: bytes


def _find_query_for_target(
    target_object: str,
    parsed_queries: dict[str, ParsedQuery],
    query_target_map: dict[str, str],
) -> ParsedQuery | None:
    target_norm = normalize_name(target_object)
    candidates: list[tuple[int, ParsedQuery]] = []
    for query_norm, parsed in parsed_queries.items():
        mapped_target = query_target_map.get(query_norm)
        if mapped_target and normalize_name(mapped_target) == target_norm:
            candidates.append((100, parsed))
            continue
        stripped_query = re.sub(r"\s*\d+$", "", query_norm)
        if stripped_query == target_norm:
            candidates.append((90, parsed))
        elif stripped_query and (stripped_query in target_norm or target_norm in stripped_query):
            candidates.append((70, parsed))
    return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1] if candidates else None


def _source_object_for_star(query: ParsedQuery) -> str:
    if query.select_star_aliases:
        alias = query.select_star_aliases[0]
        if alias == "*":
            return query.source_objects[0] if query.source_objects else ""
        return query.alias_map.get(alias.lower(), alias)
    return query.source_objects[0] if query.source_objects else ""


def _sql_mapping(column: SQLColumnLineage) -> dict[str, str]:
    source_object = ", ".join(column.source_objects)
    if not source_object and re.search(r"\b(GETDATE|CURRENT_DATE|CURRENT_TIMESTAMP|SYSDATE)\b", column.expression, re.I):
        source_object = "System Date / Runtime"
    elif not source_object:
        source_object = "SQL expression / constant"
    return {
        "Transformation Logic at Column Level": column.transformation_logic or column.expression or "Direct",
        "Source Object": source_object,
        "Source Column": ", ".join(column.source_columns) or column.expression,
        "Notes": column.notes,
    }


def _formula_mapping(formula: FormulaLineage, reference: dict[str, Any] | None) -> dict[str, str]:
    notes = formula.notes
    if reference and reference.get("notes"):
        notes += " Reference sample guidance: " + clean_text(reference["notes"])
    return {
        "Transformation Logic at Column Level": formula.formula,
        "Source Object": ", ".join(formula.source_objects),
        "Source Column": ", ".join(formula.source_columns),
        "Notes": notes,
    }


def _reference_mapping(reference: dict[str, Any]) -> dict[str, str]:
    source_note = f"Pattern learned during development from {reference.get('sample_workbook', 'sample output')}."
    notes = clean_text(reference.get("notes"))
    return {
        "Transformation Logic at Column Level": clean_text(reference.get("transformation_logic")) or "Direct",
        "Source Object": clean_text(reference.get("source_object")),
        "Source Column": clean_text(reference.get("source_column")),
        "Notes": f"{source_note} {notes}".strip(),
    }


def _build_cross_sheet_index(header_catalog: pd.DataFrame, query_backed: set[str]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for _, row in header_catalog[~header_catalog["Excluded"]].iterrows():
        column_norm = row["Column Normalized"]
        target = row["Target Object"]
        index.setdefault(column_norm, []).append(target)
    for column_norm, objects in index.items():
        index[column_norm] = sorted(
            list(dict.fromkeys(objects)),
            key=lambda obj: (0 if normalize_name(obj) in query_backed else 1, obj.lower()),
        )
    return index


def _manual_or_cross_mapping(
    target_object: str,
    target_column: str,
    cross_index: dict[str, list[str]],
    query_backed: set[str],
) -> dict[str, str]:
    target_norm = normalize_name(target_object)
    candidates = [obj for obj in cross_index.get(normalize_name(target_column), []) if normalize_name(obj) != target_norm]
    template_like = any(token in target_norm for token in ("template", "output", "final", "report"))
    if candidates and template_like:
        preferred = sorted(candidates, key=lambda obj: (0 if normalize_name(obj) in query_backed else 1, obj.lower()))[0]
        return {
            "Transformation Logic at Column Level": "Direct",
            "Source Object": preferred,
            "Source Column": target_column,
            "Notes": "Direct cross-sheet mapping inferred from an identical header in the same workbook; review recommended.",
        }
    return {
        "Transformation Logic at Column Level": "Direct",
        "Source Object": "Manual / Excel input",
        "Source Column": target_column,
        "Notes": "No explicit SQL or formula lineage was found; treated as a direct/manual input based on metadata headers.",
    }


def generate_etl_mapping(file_bytes: bytes, filename: str) -> GenerationResult:
    metadata: MetadataWorkbook = parse_metadata_workbook(file_bytes, filename)
    header_catalog = build_header_catalog(metadata)
    query_target_map = build_query_target_map(metadata)

    parsed_queries: dict[str, ParsedQuery] = {}
    for row in get_power_query_rows(metadata):
        parsed = parse_power_query_sql(row["query_name"], row["m_code"])
        parsed_queries[normalize_name(parsed.query_name)] = parsed
        parsed_queries.setdefault(re.sub(r"\s*\d+$", "", normalize_name(parsed.query_name)), parsed)

    formulas = parse_formula_rows(get_formula_rows(metadata))
    formula_index = index_formulas(formulas)
    references = ReferenceRuleLibrary()

    query_by_target: dict[str, ParsedQuery] = {}
    for target in header_catalog[~header_catalog["Excluded"]]["Target Object"].drop_duplicates():
        query = _find_query_for_target(target, parsed_queries, query_target_map)
        if query:
            query_by_target[normalize_name(target)] = query
    query_backed = set(query_by_target)
    cross_index = _build_cross_sheet_index(header_catalog, query_backed)

    rows: list[dict[str, str]] = []
    for _, header in header_catalog[~header_catalog["Excluded"]].iterrows():
        target_object = header["Target Object"]
        target_column = header["Target Column"]
        object_norm = header["Object Normalized"]
        column_norm = header["Column Normalized"]
        reference = references.find(target_object, target_column)
        formula = formula_index.get((object_norm, column_norm))
        query = query_by_target.get(object_norm)
        mapping: dict[str, str] | None = None

        if formula:
            mapping = _formula_mapping(formula, reference)
        elif query:
            sql_index = {normalize_name(item.target_column): item for item in query.columns}
            sql_column = sql_index.get(column_norm)
            if sql_column:
                mapping = _sql_mapping(sql_column)
            elif query.select_star_aliases:
                source_object = _source_object_for_star(query)
                mapping = {
                    "Transformation Logic at Column Level": "Direct",
                    "Source Object": source_object,
                    "Source Column": target_column,
                    "Notes": f"Expanded from SELECT * in SQL query {query.query_name}; header metadata supplies the column list.",
                }
            elif reference:
                mapping = _reference_mapping(reference)
            else:
                source_object = query.source_objects[0] if len(query.source_objects) == 1 else ", ".join(query.source_objects)
                mapping = {
                    "Transformation Logic at Column Level": "Direct",
                    "Source Object": source_object,
                    "Source Column": target_column,
                    "Notes": f"Column inferred against SQL query {query.query_name}; explicit SELECT lineage was not conclusive. Review recommended.",
                }
        elif reference:
            mapping = _reference_mapping(reference)
        else:
            mapping = _manual_or_cross_mapping(target_object, target_column, cross_index, query_backed)

        rows.append(
            {
                "Target Object": target_object,
                "Target Column": target_column,
                **mapping,
                "_Object Order": int(header["Object Order"]),
                "_Column No": int(header["Column No"]),
            }
        )

    mapping_df = pd.DataFrame(rows)
    if mapping_df.empty:
        raise ValueError("No valid ETL mapping rows could be generated from the metadata workbook.")

    mapping_df["_Dedup Key"] = mapping_df.apply(
        lambda row: "|".join(
            [
                normalize_name(row["Target Object"]),
                normalize_name(row["Target Column"]),
                normalize_name(row["Source Object"]),
                normalize_name(row["Source Column"]),
                normalize_name(row["Transformation Logic at Column Level"]),
            ]
        ),
        axis=1,
    )
    mapping_df = (
        mapping_df.drop_duplicates("_Dedup Key", keep="first")
        .sort_values(["_Object Order", "_Column No", "Target Object", "Target Column"], kind="stable")
        .reset_index(drop=True)
    )
    mapping_df = mapping_df[OUTPUT_COLUMNS]

    coverage = compare_coverage(header_catalog, mapping_df)
    excel_bytes = build_output_excel(mapping_df, coverage)
    return GenerationResult(mapping=mapping_df, coverage=coverage, excel_bytes=excel_bytes)
