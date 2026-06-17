# ETL Mapping Spec Automation

A reusable Python and Streamlit application that reverse-engineers an Excel report metadata workbook into an ETL Mapping Specification Document.

## Runtime input

The deployed application takes **one input only**:

- Metadata workbook (`.xlsx` or `.xlsm`)

The sample metadata and sample output files under `development_samples/` were used once to establish reusable reverse-mortgage mapping patterns. They are not required in the Streamlit user interface.

## Generated output

The generated workbook is named:

`ETL_Mapping_Specification_Document.xlsx`

It contains exactly two sheets:

1. `ETL Mapping Specification`
   - Target Object
   - Target Column
   - Transformation Logic at Column Level
   - Source Object
   - Source Column
   - Notes

2. `Coverage Verification`
   - Coverage summary
   - Metadata Header Pivot
   - Generated ETL Mapping Pivot
   - All mismatch explanations and skipped-object explanations in the same sheet

The application will not generate more than three sheets. The current implementation intentionally uses only two.

## Validation behavior

The application compares the `Headers` metadata sheet against the generated mapping by:

- Sheet/Target Object name
- Column name
- Column count

Names are normalized for comparison. Derived objects containing terms such as Pivot, Pivot Table, Summary, Dashboard, Chart, Report Results, or Aggregate are allowed exclusions and are explained in `Coverage Verification`.

## SQL parsing behavior

Power Query M code is decoded to retrieve embedded SQL. The SQL parser extracts:

- SELECT expressions and aliases
- Source tables/views and aliases
- Joins
- WHERE filters
- CASE expressions
- Date conversion logic
- Arithmetic/calculated expressions
- SELECT * lineage expanded using metadata headers

When SQL lineage is inconclusive, the application uses formula metadata, learned development reference rules, cross-sheet header matches, or a clearly marked governed inference.

## Run on Windows

1. Extract the package.
2. Double-click `run_app.bat`.

Or run:

```bat
run_app.bat
```

## Run manually

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Run on macOS/Linux

```bash
chmod +x run_app.sh
./run_app.sh
```

## Development sample files

- `development_samples/metadata/` contains the supplied `RE_Ext_*` metadata examples.
- `development_samples/sample_outputs/` contains the supplied sample mapping outputs detected in `sample_re_outputs.zip`.
- `reference_mapping_rules.json` is the embedded one-time learning library generated from those samples.
