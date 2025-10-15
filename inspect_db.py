# inspect_db.py
from __future__ import annotations

import argparse
from datetime import date as _date, datetime as _dt
from typing import Optional

from sqlalchemy import and_

from models import SessionLocal, Appointment, init_db


def parse_date(s: Optional[str]) -> Optional[_date]:
    if not s:
        return None
    # Accept YYYY-MM-DD, MM/DD, MM-DD
    for fmt in ("%Y-%m-%d", "%m/%d", "%m-%d"):
        try:
            dt = _dt.strptime(s, fmt)
            # If year missing, assume current year
            year = dt.year if fmt == "%Y-%m-%d" else _date.today().year
            return _date(year, dt.month, dt.day)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"Invalid date: {s}")


def main():
    parser = argparse.ArgumentParser(
        description="Print appointments from SQLite with optional date range."
    )
    parser.add_argument("--from", dest="start", type=parse_date, help="Start date (YYYY-MM-DD or MM/DD)")
    parser.add_argument("--to", dest="end", type=parse_date, help="End date (YYYY-MM-DD or MM/DD)")
    parser.add_argument("--limit", type=int, default=200, help="Max rows (default 200)")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        q = db.query(Appointment)

        if args.start and args.end:
            q = q.filter(and_(Appointment.date >= args.start, Appointment.date <= args.end))
        elif args.start:
            q = q.filter(Appointment.date >= args.start)
        elif args.end:
            q = q.filter(Appointment.date <= args.end)

        q = q.order_by(Appointment.date, Appointment.start_time).limit(args.limit)
        rows = q.all()

        if not rows:
            rng = ""
            if args.start or args.end:
                rng = f" in range [{args.start or '-∞'} .. {args.end or '+∞'}]"
            print(f"No appointments found{rng}.")
            return

        # Pretty print
        print(f"{'ID':>3}  {'DATE':<10}  {'START–END':<13}  {'TITLE / DESCRIPTION'}")
        print("-" * 70)
        for a in rows:
            title = (getattr(a, "title", None) or a.description or "").strip()
            when = f"{a.start_time.strftime('%H:%M')}–{a.end_time.strftime('%H:%M')}"
            print(f"{a.id:>3}  {a.date.isoformat():<10}  {when:<13}  {title}")

        print("-" * 70)
        print(f"{len(rows)} row(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()