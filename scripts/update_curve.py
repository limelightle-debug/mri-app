"""The US Treasury yield curve for the institute's morning paper: data/curve.json.

Source: the Treasury's daily par yield curve (home.treasury.gov), 1 month to 30 years. Keeps the latest
day's curve, the curves 3 and 6 months earlier, and the 10Y-2Y and 10Y-3M spreads day by day for the last 5 years.
Writes only when the latest day changes.
"""
import csv
import io
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "curve.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
       "?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
TENORS = [("1 Mo", "1M", 1 / 12), ("3 Mo", "3M", .25), ("6 Mo", "6M", .5), ("1 Yr", "1Y", 1), ("2 Yr", "2Y", 2),
          ("3 Yr", "3Y", 3), ("5 Yr", "5Y", 5), ("7 Yr", "7Y", 7), ("10 Yr", "10Y", 10), ("20 Yr", "20Y", 20),
          ("30 Yr", "30Y", 30)]


def year_rows(y):
    r = requests.get(URL.format(y=y), headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    out = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        d = datetime.strptime(row["Date"], "%m/%d/%Y").date()
        vals = {}
        for col, k, _ in TENORS:
            v = (row.get(col) or "").strip()
            if v and v.upper() != "N/A":
                vals[k] = float(v)
        if "2Y" in vals and "10Y" in vals:
            out[d] = vals
    return out


def main():
    today = date.today()
    rows = {}
    for y in range(today.year - 5, today.year + 1):
        try:
            rows.update(year_rows(y))
        except Exception as e:  # noqa: BLE001  (an old year failing must not stop the rest)
            print(f"{y}: {e}", file=sys.stderr)
    if not rows:
        sys.exit("no curve data")
    days = sorted(rows)
    last = days[-1]
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if old.get("date") == last.isoformat() and "m3" in old:
        return

    def on_or_before(d):
        c = [x for x in days if x <= d]
        return c[-1] if c else days[0]

    snap = lambda d: {"date": d.isoformat(), "y": rows[d]}
    out = {
        "date": last.isoformat(),
        "tenors": [[k, yrs] for _, k, yrs in TENORS],
        "now": snap(last),
        "m3": snap(on_or_before(last - timedelta(days=91))),
        "m6": snap(on_or_before(last - timedelta(days=182))),
        # day by day: [date, 10Y-2Y, 10Y-3M]
        "spread": [[d.strftime("%Y%m%d"), round(rows[d]["10Y"] - rows[d]["2Y"], 2),
                    round(rows[d]["10Y"] - rows[d]["3M"], 2) if "3M" in rows[d] else None] for d in days],
        "source": "U.S. Treasury daily par yield curve",
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(last, rows[last])


if __name__ == "__main__":
    main()
