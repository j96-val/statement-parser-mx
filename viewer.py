"""
Phase 8: local Streamlit viewer over the SQLite history DB. Read-only except
for one write path (category correction). Data never leaves the machine -
`streamlit run viewer.py` starts a local server only.

Run: pip install -r requirements-viewer.txt && streamlit run viewer.py
"""
import os

import pandas as pd
import streamlit as st

import db
from categorize import RULES

st.set_page_config(page_title="Statement Parser MX", layout="wide")


@st.cache_data(show_spinner=False)
def load_data(_mtime: float):
    # _mtime is the DB file's mtime, unused otherwise - just makes the cache
    # key change (and reload) whenever the DB is written to.
    conn = db.connect()
    db.init_db(conn)
    return db.fetch_dataframe(conn), db.fetch_statements(conn)


def db_mtime() -> float:
    return os.path.getmtime(db.DEFAULT_DB) if db.DEFAULT_DB.exists() else 0.0


df, stmts = load_data(db_mtime())

if df.empty:
    st.title("Statement Parser MX")
    st.info("No transactions yet. Run `python3 build_report.py` first.")
    st.stop()

ALL_CATEGORIES = sorted(set(df["Category"].unique()) | {c for c, _ in RULES})

st.sidebar.header("Filters")
banks = st.sidebar.multiselect("Bank", sorted(df["Bank"].unique()))
categories = st.sidebar.multiselect("Category", ALL_CATEGORIES)
months = st.sidebar.multiselect("Month", sorted(df["Month"].unique()))

filtered = df.copy()
if banks:
    filtered = filtered[filtered["Bank"].isin(banks)]
if categories:
    filtered = filtered[filtered["Category"].isin(categories)]
if months:
    filtered = filtered[filtered["Month"].isin(months)]

st.title("Statement Parser MX")

charges = filtered[filtered["Type"] == "charge"]
payments = filtered[filtered["Type"] == "payment"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Charges", f"${charges['Amount'].sum():,.2f}")
c2.metric("Total Payments", f"${-payments['Amount'].sum():,.2f}")
c3.metric("Net", f"${filtered['Amount'].sum():,.2f}")
c4.metric("Transactions", len(filtered))

col1, col2 = st.columns(2)
with col1:
    st.subheader("Monthly spend trend")
    trend = charges.groupby("Month")["Amount"].sum()
    st.line_chart(trend)
with col2:
    st.subheader("Spend by category")
    by_cat = charges.groupby("Category")["Amount"].sum().sort_values(ascending=False)
    st.bar_chart(by_cat)

if len(stmts):
    st.subheader("Statements")
    stmts_view = stmts.copy()
    stmts_view["Utilization %"] = (
        stmts_view["ClosingBalance"] / stmts_view["CreditLimit"] * 100
    ).round(1)
    st.dataframe(stmts_view, width="stretch", hide_index=True)

st.subheader("Transactions (edit Category to correct it)")
# data_editor's returned frame always has a fresh 0..n-1 index, regardless of
# the input's index - reset filtered to match so the comparison below aligns
# by position instead of raising on label mismatch after any filter narrows
# the row set to a non-contiguous slice of the original index.
filtered = filtered.reset_index(drop=True)
edited = st.data_editor(
    filtered,
    width="stretch",
    hide_index=True,
    disabled=[c for c in filtered.columns if c != "Category"],
    column_config={
        "Category": st.column_config.SelectboxColumn(options=ALL_CATEGORIES),
    },
    key="txn_editor",
)

changed = edited[edited["Category"] != filtered["Category"]]
if len(changed):
    conn = db.connect()
    for _, row in changed.iterrows():
        db.set_override(conn, row["Description"], row["Category"])
    st.cache_data.clear()
    st.rerun()
