from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from typing import Any

import pandas as pd

from config import EXCLUDED_OBJECT_TERMS, KNOWN_METADATA_SHEETS


def normalize_name(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.strip().lower().replace("_", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def is_excluded_object(name: str) -> bool:
    normalized = normalize_name(name)
    if not normalized:
        return True
    return any(term == normalized or term in normalized for term in EXCLUDED_OBJECT_TERMS)


def _find_column(df: pd.DataFrame, *candidates: str) -> str | None:
    lookup = {normalize_name(col): col for col in df.columns}
    for candidate in candidates:
        found = lookup.get(normalize_name(candidate))
        if found is not None:
            return found
    return None


@dataclass
class MetadataWorkbook:
    filename: str
    sheets: dict[str, pd.DataFrame]
    headers: pd.DataFrame
    workbook_sheets: pd.DataFrame
    power_queries: pd.DataFrame
    data_sources: pd.DataFrame
    excel_tables: pd.DataFrame
    formulas: pd.DataFrame
    dropdowns: pd.DataFrame

    @property
    def sheet_names(self) -> list[str]:
        return list(self.sheets)


def parse_metadata_workbook(file_bytes: bytes, filename: str) -> MetadataWorkbook:
    if not file_bytes:
        raise ValueError("The metadata workbook is empty.")

    try:
        excel = pd.ExcelFile(BytesIO(file_bytes), engine="openpyxl")
    except Exception as exc:
        raise ValueError(f"Unable to read metadata workbook: {exc}") from exc

    sheets: dict[str, pd.DataFrame] = {}
    for sheet_name in excel.sheet_names:
        try:
            frame = pd.read_excel(excel, sheet_name=sheet_name, dtype=object)
        except Exception:
            frame = pd.DataFrame()
        frame.columns = [clean_text(col) for col in frame.columns]
        sheets[sheet_name] = frame

    normalized_sheet_lookup = {normalize_name(name): name for name in sheets}

    def get_known(key: str) -> pd.DataFrame:
        expected = KNOWN_METADATA_SHEETS[key]
        actual = normalized_sheet_lookup.get(normalize_name(expected))
        return sheets.get(actual, pd.DataFrame()).copy() if actual else pd.DataFrame()

    metadata = MetadataWorkbook(
        filename=filename,
        sheets=sheets,
        headers=get_known("headers"),
        workbook_sheets=get_known("workbook_sheets"),
        power_queries=get_known("power_query_m_code"),
        data_sources=get_known("data_sources"),
        excel_tables=get_known("excel_tables"),
        formulas=get_known("formulas_sample"),
        dropdowns=get_known("dropdowns_sample"),
    )

    if metadata.headers.empty:
        raise ValueError("The workbook does not contain a readable Headers metadata sheet.")
    return metadata


def build_header_catalog(metadata: MetadataWorkbook) -> pd.DataFrame:
    df = metadata.headers.copy()
    sheet_col = _find_column(df, "Sheet Name")
    header_col = _find_column(df, "Header Name")
    column_no_col = _find_column(df, "Column No", "Column Number")
    header_row_col = _find_column(df, "Header Row")

    if sheet_col is None or header_col is None:
        raise ValueError("Headers sheet must contain Sheet Name and Header Name columns.")

    result = pd.DataFrame(
        {
            "Target Object": df[sheet_col].map(clean_text),
            "Target Column": df[header_col].map(clean_text),
            "Column No": pd.to_numeric(df[column_no_col], errors="coerce") if column_no_col else range(1, len(df) + 1),
            "Header Row": pd.to_numeric(df[header_row_col], errors="coerce") if header_row_col else 1,
        }
    )
    result = result[(result["Target Object"] != "") & (result["Target Column"] != "")].copy()
    result["Object Normalized"] = result["Target Object"].map(normalize_name)
    result["Column Normalized"] = result["Target Column"].map(normalize_name)
    result["Excluded"] = result["Target Object"].map(is_excluded_object)
    result["Column No"] = result["Column No"].fillna(999999).astype(int)
    result = result.drop_duplicates(["Object Normalized", "Column Normalized"], keep="first")

    # Preserve workbook sheet order where available.
    order: dict[str, int] = {}
    ws = metadata.workbook_sheets
    if not ws.empty:
        ws_sheet_col = _find_column(ws, "Sheet Name")
        if ws_sheet_col:
            for idx, value in enumerate(ws[ws_sheet_col].tolist()):
                order.setdefault(normalize_name(value), idx)
    result["Object Order"] = result["Object Normalized"].map(lambda x: order.get(x, 999999))
    return result.sort_values(["Object Order", "Column No", "Target Column"], kind="stable").reset_index(drop=True)


def build_query_target_map(metadata: MetadataWorkbook) -> dict[str, str]:
    """Return normalized query name -> report sheet/target object."""
    mapping: dict[str, str] = {}
    tables = metadata.excel_tables
    if not tables.empty:
        sheet_col = _find_column(tables, "Sheet Name")
        table_col = _find_column(tables, "Table Name")
        connection_col = _find_column(tables, "Connection Name")
        for _, row in tables.iterrows():
            sheet = clean_text(row.get(sheet_col, "")) if sheet_col else ""
            table = clean_text(row.get(table_col, "")) if table_col else ""
            connection = clean_text(row.get(connection_col, "")) if connection_col else ""
            if not sheet:
                continue
            candidates = [table, connection]
            if connection.lower().startswith("query -"):
                candidates.append(connection.split("-", 1)[1].strip())
            for candidate in candidates:
                normalized = normalize_name(candidate)
                normalized_without_suffix = re.sub(r"\s*\d+$", "", normalized)
                if normalized:
                    mapping.setdefault(normalized, sheet)
                if normalized_without_suffix:
                    mapping.setdefault(normalized_without_suffix, sheet)

    # Fall back to a direct query-name-to-sheet-name match.
    for sheet_name in build_header_catalog(metadata)["Target Object"].drop_duplicates().tolist():
        mapping.setdefault(normalize_name(sheet_name), sheet_name)
    return mapping


def get_power_query_rows(metadata: MetadataWorkbook) -> list[dict[str, str]]:
    df = metadata.power_queries
    if df.empty:
        return []
    query_col = _find_column(df, "Query Name")
    code_col = _find_column(df, "Power Query M Code")
    if not query_col or not code_col:
        return []
    return [
        {"query_name": clean_text(row[query_col]), "m_code": clean_text(row[code_col])}
        for _, row in df.iterrows()
        if clean_text(row[query_col]) and clean_text(row[code_col])
    ]


def get_formula_rows(metadata: MetadataWorkbook) -> list[dict[str, str]]:
    df = metadata.formulas
    if df.empty:
        return []
    sheet_col = _find_column(df, "Sheet Name")
    header_col = _find_column(df, "Header Name")
    original_col = _find_column(df, "Original Formula Text")
    readable_col = _find_column(df, "Readable Formula Using Headers")
    if not sheet_col or not header_col:
        return []
    rows: list[dict[str, str]] = []
    for _, row in df.iterrows():
        target_object = clean_text(row[sheet_col])
        target_column = clean_text(row[header_col])
        original = clean_text(row[original_col]) if original_col else ""
        readable = clean_text(row[readable_col]) if readable_col else ""
        if target_object and target_column and (original or readable):
            rows.append(
                {
                    "target_object": target_object,
                    "target_column": target_column,
                    "original_formula": original,
                    "readable_formula": readable,
                }
            )
    return rows
