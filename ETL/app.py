from __future__ import annotations

import streamlit as st

from config import OUTPUT_FILENAME
from etl_mapping_engine import generate_etl_mapping


st.set_page_config(page_title="ETL Mapping Spec Automation", layout="wide")
st.title("ETL Mapping Spec Automation")
st.caption("Upload one reverse-engineered Excel metadata workbook to generate the ETL Mapping Specification and coverage verification.")

uploaded_file = st.file_uploader("Metadata Workbook", type=["xlsx", "xlsm"])

if st.button("Generate ETL Mapping Specification", type="primary", disabled=uploaded_file is None):
    try:
        with st.spinner("Analyzing metadata, SQL lineage, formulas, and coverage..."):
            result = generate_etl_mapping(uploaded_file.getvalue(), uploaded_file.name)
        st.session_state["generation_result"] = result
        st.success("ETL Mapping Specification generated successfully.")
    except Exception as exc:
        st.session_state.pop("generation_result", None)
        st.error(f"Generation failed: {exc}")

result = st.session_state.get("generation_result")
if result is not None:
    st.subheader("ETL Mapping Specification Preview")
    st.dataframe(result.mapping, use_container_width=True, hide_index=True, height=520)

    st.subheader("Coverage Verification")
    summary = result.coverage.summary
    metric_cols = st.columns(5)
    metric_cols[0].metric("Coverage", f"{summary['Coverage Percentage']}%")
    metric_cols[1].metric("Metadata Columns", int(summary["Metadata Columns Considered"]))
    metric_cols[2].metric("Generated Columns", int(summary["Generated Target Columns"]))
    metric_cols[3].metric("Missing", int(summary["Missing Columns"]))
    metric_cols[4].metric("Skipped Objects", int(summary["Skipped Derived Objects"]))

    left, right = st.columns(2)
    with left:
        st.markdown("**Metadata Header Pivot**")
        st.dataframe(result.coverage.metadata_pivot, use_container_width=True, hide_index=True, height=340)
    with right:
        st.markdown("**Generated Mapping Pivot**")
        st.dataframe(result.coverage.generated_pivot, use_container_width=True, hide_index=True, height=340)

    if result.coverage.exceptions.empty:
        st.success("Header and target-column coverage matches after permitted exclusions.")
    else:
        st.warning("Coverage exceptions were identified. Explanations are included in the output workbook.")
        st.dataframe(result.coverage.exceptions, use_container_width=True, hide_index=True, height=320)

    st.download_button(
        "Download ETL Mapping Specification",
        data=result.excel_bytes,
        file_name=OUTPUT_FILENAME,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
