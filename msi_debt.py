"""
Phase 4.3: projects committed MSI (meses sin intereses / interest-free
installment) debt forward from the DB's installment columns (Phase 4.1).

Only Invex currently populates InstallmentNum/InstallmentTotal - Banorte's
installments are intentionally folded into its regular-section rows instead
of tracked separately (see parsers/banorte.py's module docstring), so they
never appear here. No bank prints this consolidated forward view itself.
"""
from datetime import date

import pandas as pd


def _add_months(d: date, n: int) -> date:
    return (pd.Timestamp(d) + pd.DateOffset(months=n)).date()


def active_msi(df: pd.DataFrame) -> pd.DataFrame:
    """One row per still-active MSI purchase, at its latest known
    installment_num, with a computed Remaining (months left) and EndMonth."""
    if "InstallmentTotal" not in df.columns:
        return df.iloc[0:0]
    msi = df[df["InstallmentTotal"].notna()].copy()
    if msi.empty:
        return msi

    msi["StatementDate"] = pd.to_datetime(msi["StatementDate"])
    # Same purchase reappears every statement with a rising InstallmentNum but
    # the same total/original amount - keep only the latest snapshot, which
    # carries the current installment_num.
    group_cols = ["Bank", "Description", "InstallmentTotal", "OriginalAmount"]
    latest = msi.loc[msi.groupby(group_cols)["StatementDate"].idxmax()].copy()

    latest["Remaining"] = (latest["InstallmentTotal"] - latest["InstallmentNum"]).clip(lower=0).astype(int)
    latest = latest[latest["Remaining"] > 0]
    latest["EndMonth"] = latest.apply(
        lambda r: _add_months(r["StatementDate"].date(), int(r["Remaining"])).strftime("%Y-%m"),
        axis=1,
    )
    return latest


def monthly_projection(active: pd.DataFrame, months_ahead: int = 12) -> list[tuple[str, float]]:
    """[(month, total_committed), ...] ascending, for the soonest months_ahead
    months that carry a committed installment payment."""
    totals: dict[str, float] = {}
    for _, row in active.iterrows():
        start = row["StatementDate"].date()
        for m in range(1, int(row["Remaining"]) + 1):
            key = _add_months(start, m).strftime("%Y-%m")
            totals[key] = totals.get(key, 0.0) + row["Amount"]
    return sorted(totals.items())[:months_ahead]
