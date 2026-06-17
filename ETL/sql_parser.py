from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable

try:
    import sqlparse
except ImportError:  # Runtime installer supplies sqlparse; fallback keeps local validation functional.
    sqlparse = None

from metadata_parser import normalize_name


@dataclass
class SQLColumnLineage:
    target_column: str
    expression: str
    source_objects: list[str] = field(default_factory=list)
    source_columns: list[str] = field(default_factory=list)
    transformation_logic: str = ""
    notes: str = ""


@dataclass
class ParsedQuery:
    query_name: str
    sql: str
    columns: list[SQLColumnLineage]
    source_objects: list[str]
    alias_map: dict[str, str]
    where_clause: str
    join_summary: str
    select_star_aliases: list[str]


def decode_m_text(text: str) -> str:
    replacements = {
        "#(lf)": "\n",
        "#(cr)": "\r",
        "#(tab)": "\t",
        "_x000D_": "",
        "#(quot)": '"',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def extract_embedded_sql(m_code: str) -> str:
    decoded = decode_m_text(m_code)
    marker = re.search(r"\[\s*Query\s*=\s*\"", decoded, flags=re.I)
    if not marker:
        return decoded
    start = marker.end()
    chars: list[str] = []
    i = start
    while i < len(decoded):
        char = decoded[i]
        if char == '"':
            if i + 1 < len(decoded) and decoded[i + 1] == '"':
                chars.append('"')
                i += 2
                continue
            # End of the M string when followed by ] or ) after whitespace.
            tail = decoded[i + 1 : i + 12]
            if re.match(r"\s*[\]\)]", tail):
                break
        chars.append(char)
        i += 1
    return "".join(chars).strip()


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _split_top_level(text: str, delimiter: str = ",") -> list[str]:
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    quote: str | None = None
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            buffer.append(char)
            if char == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    buffer.append(text[i + 1])
                    i += 1
                else:
                    quote = None
        else:
            if char in {"'", '"'}:
                quote = char
                buffer.append(char)
            elif char == "(":
                depth += 1
                buffer.append(char)
            elif char == ")":
                depth = max(0, depth - 1)
                buffer.append(char)
            elif char == delimiter and depth == 0:
                parts.append("".join(buffer).strip())
                buffer = []
            else:
                buffer.append(char)
        i += 1
    if buffer:
        parts.append("".join(buffer).strip())
    return [part for part in parts if part]


def _clean_identifier(value: str) -> str:
    value = value.strip().strip("[]`\"")
    return re.sub(r"\s+", " ", value)


def _extract_sources(sql: str) -> tuple[list[str], dict[str, str], str]:
    pattern = re.compile(
        r"\b(FROM|JOIN)\s+([\[\]A-Za-z0-9_.$#]+)(?:\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*))?",
        re.I,
    )
    objects: list[str] = []
    alias_map: dict[str, str] = {}
    joins: list[str] = []
    reserved = {"where", "left", "right", "inner", "outer", "full", "cross", "join", "on", "order", "group"}
    for match in pattern.finditer(sql):
        kind, raw_object, raw_alias = match.groups()
        source_object = _clean_identifier(raw_object)
        alias = _clean_identifier(raw_alias or "")
        if alias.lower() in reserved:
            alias = ""
        if source_object not in objects:
            objects.append(source_object)
        alias_map[source_object.lower()] = source_object
        alias_map[source_object.split(".")[-1].strip("[]").lower()] = source_object
        if alias:
            alias_map[alias.lower()] = source_object
        if kind.upper() == "JOIN":
            joins.append(source_object)
    return objects, alias_map, ", ".join(joins)


def _extract_where(sql: str) -> str:
    match = re.search(r"\bWHERE\b(.*?)(?=\bGROUP\s+BY\b|\bORDER\s+BY\b|\bHAVING\b|;|$)", sql, flags=re.I | re.S)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()[:1000]


def _extract_select_body(sql: str) -> str:
    match = re.search(r"\bSELECT\b\s+(?:DISTINCT\s+)?(.*?)\bFROM\b", sql, flags=re.I | re.S)
    return match.group(1).strip() if match else ""


def _detect_alias(expression: str) -> tuple[str, str]:
    expression = expression.strip()
    as_match = re.match(r"(?is)^(.*)\s+AS\s+([\[\]A-Za-z0-9_# .-]+)$", expression)
    if as_match:
        return as_match.group(1).strip(), _clean_identifier(as_match.group(2))

    # Conservative trailing alias detection for expressions/functions.
    trailing = re.match(r"(?is)^(.*(?:\)|\]|'|\d))\s+([A-Za-z_][A-Za-z0-9_#]*)$", expression)
    if trailing and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_*][A-Za-z0-9_*]*$", expression):
        return trailing.group(1).strip(), _clean_identifier(trailing.group(2))

    direct = re.match(r"(?is)^([A-Za-z_][A-Za-z0-9_]*)\.([\[\]A-Za-z0-9_#]+)$", expression)
    if direct:
        return expression, _clean_identifier(direct.group(2))
    return expression, _clean_identifier(expression.split(".")[-1])


def _column_references(expression: str, alias_map: dict[str, str]) -> tuple[list[str], list[str]]:
    refs = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.\[?([A-Za-z_][A-Za-z0-9_#$ ]*)\]?", expression)
    objects: list[str] = []
    columns: list[str] = []
    for alias, column in refs:
        source_object = alias_map.get(alias.lower(), alias)
        column = _clean_identifier(column)
        if source_object not in objects:
            objects.append(source_object)
        if column not in columns:
            columns.append(column)
    return objects, columns


def _business_logic(expression: str, target_column: str, source_columns: list[str]) -> str:
    compact = re.sub(r"\s+", " ", expression).strip()
    direct_match = re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.\[?[A-Za-z_][A-Za-z0-9_#$ ]*\]?", compact)
    if direct_match:
        source = source_columns[0] if source_columns else target_column
        return "Direct" if normalize_name(source) == normalize_name(target_column) else f"Renamed from {source}"
    return compact[:4000]


def parse_power_query_sql(query_name: str, m_code: str) -> ParsedQuery:
    sql = _strip_comments(extract_embedded_sql(m_code))
    if sqlparse is not None:
        sql = sqlparse.format(sql, strip_comments=True, reindent=False, keyword_case="upper")
    source_objects, alias_map, join_summary = _extract_sources(sql)
    where_clause = _extract_where(sql)
    select_body = _extract_select_body(sql)
    select_items = _split_top_level(select_body)
    columns: list[SQLColumnLineage] = []
    star_aliases: list[str] = []

    for item in select_items:
        item = item.strip()
        star_match = re.fullmatch(r"(?i)([A-Za-z_][A-Za-z0-9_]*)\.\*|\*", item)
        if star_match:
            star_aliases.append(star_match.group(1) if star_match.group(1) else "*")
            continue
        expression, target_column = _detect_alias(item)
        src_objects, src_columns = _column_references(expression, alias_map)
        if not src_objects and len(source_objects) == 1:
            src_objects = source_objects[:]
        notes = f"Parsed from SQL query {query_name}."
        if join_summary:
            notes += f" Joins include: {join_summary}."
        if where_clause:
            notes += f" Source filter: {where_clause}."
        columns.append(
            SQLColumnLineage(
                target_column=target_column,
                expression=expression,
                source_objects=src_objects,
                source_columns=src_columns,
                transformation_logic=_business_logic(expression, target_column, src_columns),
                notes=notes,
            )
        )

    return ParsedQuery(
        query_name=query_name,
        sql=sql,
        columns=columns,
        source_objects=source_objects,
        alias_map=alias_map,
        where_clause=where_clause,
        join_summary=join_summary,
        select_star_aliases=star_aliases,
    )


def index_query_columns(parsed_queries: Iterable[ParsedQuery]) -> dict[str, dict[str, SQLColumnLineage]]:
    result: dict[str, dict[str, SQLColumnLineage]] = {}
    for query in parsed_queries:
        result[normalize_name(query.query_name)] = {
            normalize_name(column.target_column): column for column in query.columns if column.target_column
        }
    return result
