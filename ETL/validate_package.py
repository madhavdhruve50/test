from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from etl_mapping_engine import generate_etl_mapping


def main() -> None:
    root = Path(__file__).resolve().parent
    metadata_files = sorted((root / "development_samples" / "metadata").glob("RE_Ext_*.xlsx"))
    if not metadata_files:
        raise SystemExit("No sample metadata files found.")
    for path in metadata_files:
        result = generate_etl_mapping(path.read_bytes(), path.name)
        out = root / "generated_examples" / f"Generated_{path.stem}.xlsx"
        out.write_bytes(result.excel_bytes)
        with ZipFile(out) as archive:
            workbook_xml = archive.read("xl/workbook.xml").decode("utf-8", errors="ignore")
            sheet_count = workbook_xml.count("<sheet ")
        assert sheet_count <= 3, f"{path.name}: output has {sheet_count} sheets"
        assert list(result.mapping.columns) == [
            "Target Object",
            "Target Column",
            "Transformation Logic at Column Level",
            "Source Object",
            "Source Column",
            "Notes",
        ]
        print(
            f"{path.name}: rows={len(result.mapping)}, coverage={result.coverage.summary['Coverage Percentage']}%, sheets={sheet_count}"
        )


if __name__ == "__main__":
    main()
