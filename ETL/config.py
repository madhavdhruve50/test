from __future__ import annotations

OUTPUT_COLUMNS = [
    "Target Object",
    "Target Column",
    "Transformation Logic at Column Level",
    "Source Object",
    "Source Column",
    "Notes",
]

KNOWN_METADATA_SHEETS = {
    "workbook_sheets": "Workbook_Sheets",
    "headers": "Headers",
    "power_query_m_code": "Power_Query_M_Code",
    "data_sources": "Data_Sources",
    "excel_tables": "Excel_Tables",
    "formulas_sample": "Formulas_Sample",
    "dropdowns_sample": "Dropdowns_Sample",
}

EXCLUDED_OBJECT_TERMS = {
    "pivot",
    "pivot table",
    "pivot tables",
    "dashboard",
    "dashboards",
    "chart",
    "charts",
    "summary",
    "summaries",
    "report result",
    "report results",
    "aggregate",
    "aggregation",
}

OUTPUT_FILENAME = "ETL_Mapping_Specification_Document.xlsx"
MAPPING_SHEET = "ETL Mapping Specification"
VERIFICATION_SHEET = "Coverage Verification"
