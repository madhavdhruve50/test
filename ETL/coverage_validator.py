from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

from metadata_parser import is_excluded_object, normalize_name


@dataclass
class CoverageResult:
    metadata_pivot: pd.DataFrame
    generated_pivot: pd.DataFrame
    exceptions: pd.DataFrame
    summary: dict[str, float | int | str]


def _pivot(df: pd.DataFrame, object_col: str, column_col: str, object_label: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for obj, group in df.groupby(object_col, sort=False):
        names = [str(value).strip() for value in group[column_col].tolist() if str(value).strip()]
        unique_names = list(dict.fromkeys(names))
        rows.append(
            {
                object_label: obj,
                "Column Count": len(unique_names),
                "Column Names": " | ".join(unique_names),
            }
        )
    return pd.DataFrame(rows)


def compare_coverage(header_catalog: pd.DataFrame, mapping_df: pd.DataFrame) -> CoverageResult:
    considered = header_catalog[~header_catalog["Excluded"]].copy()
    skipped = header_catalog[header_catalog["Excluded"]].copy()

    metadata_base = considered[["Target Object", "Target Column"]].drop_duplicates()
    generated_base = mapping_df[["Target Object", "Target Column"]].drop_duplicates()

    metadata_pivot = _pivot(metadata_base, "Target Object", "Target Column", "Metadata Sheet Name")
    generated_pivot = _pivot(generated_base, "Target Object", "Target Column", "Generated Target Object")

    metadata_keys = {
        (normalize_name(row["Target Object"]), normalize_name(row["Target Column"])): row
        for _, row in metadata_base.iterrows()
    }
    generated_keys = {
        (normalize_name(row["Target Object"]), normalize_name(row["Target Column"])): row
        for _, row in generated_base.iterrows()
    }

    exceptions: list[dict[str, object]] = []
    for key, row in metadata_keys.items():
        if key not in generated_keys:
            exceptions.append(
                {
                    "Metadata Sheet Name": row["Target Object"],
                    "Generated Target Object": "",
                    "Metadata Column Name": row["Target Column"],
                    "Generated Target Column": "",
                    "Exception Type": "Missing Target Column",
                    "Reason / Explanation": "Column exists in metadata Headers but no mapping row was generated.",
                    "Recommended Action": "Review SQL, formula, query-to-sheet relationship, or add a governed inference rule.",
                }
            )

    for key, row in generated_keys.items():
        if key not in metadata_keys:
            exceptions.append(
                {
                    "Metadata Sheet Name": "",
                    "Generated Target Object": row["Target Object"],
                    "Metadata Column Name": "",
                    "Generated Target Column": row["Target Column"],
                    "Exception Type": "Extra Generated Target Column",
                    "Reason / Explanation": "Generated target column is not present in the metadata Headers sheet.",
                    "Recommended Action": "Confirm whether the column is formula-derived, reference-derived, or should be removed.",
                }
            )

    for obj, group in skipped.groupby("Target Object", sort=False):
        exceptions.append(
            {
                "Metadata Sheet Name": obj,
                "Generated Target Object": "",
                "Metadata Column Name": f"{group['Target Column'].nunique()} columns",
                "Generated Target Column": "",
                "Exception Type": "Skipped Derived Object",
                "Reason / Explanation": "Object was excluded because its name indicates a pivot, summary, dashboard, chart, report result, or aggregate output.",
                "Recommended Action": "No action unless the object should be treated as a physical ETL target.",
            }
        )

    exceptions_df = pd.DataFrame(
        exceptions,
        columns=[
            "Metadata Sheet Name",
            "Generated Target Object",
            "Metadata Column Name",
            "Generated Target Column",
            "Exception Type",
            "Reason / Explanation",
            "Recommended Action",
        ],
    )

    matched = len(set(metadata_keys) & set(generated_keys))
    expected = len(metadata_keys)
    coverage = round((matched / expected * 100), 2) if expected else 100.0
    missing = len(set(metadata_keys) - set(generated_keys))
    extra = len(set(generated_keys) - set(metadata_keys))
    overall = "PASS" if missing == 0 and extra == 0 else ("WARNING" if missing == 0 else "FAIL")

    summary: dict[str, float | int | str] = {
        "Overall Status": overall,
        "Metadata Target Objects Considered": metadata_base["Target Object"].nunique(),
        "Metadata Columns Considered": expected,
        "Generated Target Objects": generated_base["Target Object"].nunique(),
        "Generated Target Columns": len(generated_keys),
        "Matched Columns": matched,
        "Missing Columns": missing,
        "Extra Generated Columns": extra,
        "Skipped Derived Objects": skipped["Target Object"].nunique(),
        "Coverage Percentage": coverage,
    }
    return CoverageResult(metadata_pivot, generated_pivot, exceptions_df, summary)
