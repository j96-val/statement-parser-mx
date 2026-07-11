"""
Month-over-month spend comparison, on top of the SQLite history built by
db.py / build_report.py. Standalone read-only query, no pipeline changes.
"""
import argparse

import db


def monthly_totals(conn, category=None, type_="charge", months=6, target=None):
    """Returns [(month, total), ...] ascending, trimmed to the last `months`
    entries at or before `target` (defaults to the latest month in the DB)."""
    if target is None:
        row = conn.execute("SELECT MAX(month) AS m FROM transactions").fetchone()
        target = row["m"]
    if target is None:
        return []

    rows = conn.execute(
        """SELECT month, SUM(amount) AS total
           FROM transactions
           WHERE type = ?
             AND (? IS NULL OR UPPER(category) LIKE '%'||UPPER(?)||'%')
             AND month <= ?
           GROUP BY month ORDER BY month""",
        (type_, category, category, target),
    ).fetchall()
    result = [(r["month"], r["total"]) for r in rows]
    return result[-months:]


def main():
    parser = argparse.ArgumentParser(description="Compare category spend across months")
    parser.add_argument("--category", help="substring match, case-insensitive (omit = all)")
    parser.add_argument("--months", type=int, default=6, help="window size (default 6)")
    parser.add_argument("--type", dest="type_", default="charge", choices=["charge", "payment"])
    parser.add_argument("--month", dest="target", help="target month YYYY-MM (default: latest)")
    args = parser.parse_args()

    conn = db.connect()
    totals = monthly_totals(conn, args.category, args.type_, args.months, args.target)

    label = args.category or "All categories"
    print(f"Category: {label}   (type: {args.type_}, last {args.months} months)")
    if not totals:
        print("  No data found.")
        return

    for month, total in totals:
        print(f"  {month}     {total:>12,.2f}")

    latest_month, latest_total = totals[-1]
    prior = totals[:-1]
    if not prior:
        print(f"\nOnly one month of data ({latest_month}) - no prior average to compare.")
        return

    prior_avg = sum(t for _, t in prior) / len(prior)
    delta = latest_total - prior_avg
    pct = (delta / prior_avg * 100) if prior_avg else float("inf")
    sign = "+" if delta >= 0 else ""
    print(f"\nLatest {latest_month}: {latest_total:,.2f} vs prior avg {prior_avg:,.2f}"
          f"  ->  {sign}{delta:,.2f} ({sign}{pct:.1f}%)")


if __name__ == "__main__":
    main()
