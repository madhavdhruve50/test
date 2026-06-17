from __future__ import annotations

from io import BytesIO
import pandas as pd

from config import MAPPING_SHEET, OUTPUT_COLUMNS, VERIFICATION_SHEET
from coverage_validator import CoverageResult


def _set_mapping_widths(worksheet, body_format) -> None:
    widths = [24, 28, 58, 38, 38, 55]
    for idx, width in enumerate(widths):
        worksheet.set_column(idx, idx, width, body_format)


def build_output_excel(mapping_df: pd.DataFrame, coverage: CoverageResult) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        workbook = writer.book
        mapping_df[OUTPUT_COLUMNS].to_excel(writer, sheet_name=MAPPING_SHEET, index=False)
        mapping_ws = writer.sheets[MAPPING_SHEET]

        header_fmt = workbook.add_format(
            {
                "bold": True,
                "font_color": "#FFFFFF",
                "bg_color": "#1F4E78",
                "border": 1,
                "align": "center",
                "valign": "vcenter",
                "text_wrap": True,
            }
        )
        body_fmt = workbook.add_format({"border": 1, "valign": "top", "text_wrap": True})
        title_fmt = workbook.add_format({"bold": True, "font_size": 15, "font_color": "#1F4E78"})
        section_fmt = workbook.add_format(
            {"bold": True, "font_color": "#FFFFFF", "bg_color": "#4472C4", "border": 1}
        )
        key_fmt = workbook.add_format({"bold": True, "bg_color": "#D9EAF7", "border": 1})
        value_fmt = workbook.add_format({"border": 1})
        wrap_fmt = workbook.add_format({"border": 1, "valign": "top", "text_wrap": True})
        pass_fmt = workbook.add_format({"font_color": "#008000", "bold": True, "border": 1})
        warn_fmt = workbook.add_format({"font_color": "#9C6500", "bold": True, "border": 1})
        fail_fmt = workbook.add_format({"font_color": "#C00000", "bold": True, "border": 1})

        for col_idx, value in enumerate(OUTPUT_COLUMNS):
            mapping_ws.write(0, col_idx, value, header_fmt)
        if len(mapping_df):
            mapping_ws.set_row(0, 34)
            mapping_ws.set_default_row(48)
        _set_mapping_widths(mapping_ws, body_fmt)
        mapping_ws.freeze_panes(1, 0)
        mapping_ws.autofilter(0, 0, max(len(mapping_df), 1), len(OUTPUT_COLUMNS) - 1)

        verification_ws = workbook.add_worksheet(VERIFICATION_SHEET)
        writer.sheets[VERIFICATION_SHEET] = verification_ws
        verification_ws.write("A1", "ETL Mapping Coverage Verification", title_fmt)
        verification_ws.write("A3", "Coverage Summary", section_fmt)
        verification_ws.write("B3", "Value", section_fmt)
        row = 3
        for key, value in coverage.summary.items():
            verification_ws.write(row, 0, key, key_fmt)
            fmt = value_fmt
            if key == "Overall Status":
                fmt = pass_fmt if value == "PASS" else warn_fmt if value == "WARNING" else fail_fmt
            verification_ws.write(row, 1, value, fmt)
            row += 1

        start_row = row + 2
        verification_ws.write(start_row, 0, "Metadata Header Pivot", section_fmt)
        coverage.metadata_pivot.to_excel(writer, sheet_name=VERIFICATION_SHEET, startrow=start_row + 1, startcol=0, index=False)
        for col_idx, value in enumerate(coverage.metadata_pivot.columns):
            verification_ws.write(start_row + 1, col_idx, value, header_fmt)

        verification_ws.write(start_row, 4, "Generated ETL Mapping Pivot", section_fmt)
        coverage.generated_pivot.to_excel(writer, sheet_name=VERIFICATION_SHEET, startrow=start_row + 1, startcol=4, index=False)
        for col_idx, value in enumerate(coverage.generated_pivot.columns, start=4):
            verification_ws.write(start_row + 1, col_idx, value, header_fmt)

        exceptions_start = start_row + max(len(coverage.metadata_pivot), len(coverage.generated_pivot)) + 5
        verification_ws.write(exceptions_start, 0, "Coverage Exceptions and Explanations", section_fmt)
        if coverage.exceptions.empty:
            verification_ws.write(exceptions_start + 1, 0, "No coverage exceptions detected.", pass_fmt)
        else:
            coverage.exceptions.to_excel(
                writer, sheet_name=VERIFICATION_SHEET, startrow=exceptions_start + 1, startcol=0, index=False
            )
            for col_idx, value in enumerate(coverage.exceptions.columns):
                verification_ws.write(exceptions_start + 1, col_idx, value, header_fmt)
            verification_ws.set_row(exceptions_start + 1, 34)

        verification_ws.set_column("A:A", 30)
        verification_ws.set_column("B:B", 24)
        verification_ws.set_column("C:C", 45)
        verification_ws.set_column("D:D", 4)
        verification_ws.set_column("E:E", 30)
        verification_ws.set_column("F:F", 18)
        verification_ws.set_column("G:G", 55)
        verification_ws.freeze_panes(3, 0)

        # Apply wrapped borders to data-heavy verification areas.
        meta_end = start_row + 1 + len(coverage.metadata_pivot)
        gen_end = start_row + 1 + len(coverage.generated_pivot)
        if len(coverage.metadata_pivot):
            verification_ws.conditional_format(start_row + 2, 0, meta_end, 2, {"type": "no_blanks", "format": wrap_fmt})
        if len(coverage.generated_pivot):
            verification_ws.conditional_format(start_row + 2, 4, gen_end, 6, {"type": "no_blanks", "format": wrap_fmt})

    output.seek(0)
    return output.getvalue()
