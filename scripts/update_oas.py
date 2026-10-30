"""Corporate bond spreads for the institute's canary panel: data/oas.json.

ICE BofA option-adjusted spreads from FRED: US high yield (BAMLH0A0HYM2) and US corporate, investment grade
(BAMLC0A0CM), in %, day by day for the 3 years FRED keeps. FRED posts each day a day later. FRED answers GitHub's
runners only without a browser User-Agent, so the request carries requests' own.

{"date": "YYYY-MM-DD", "hy", "ig", "hy_d1", "ig_d1", "hist": [[YYYYMMDD, hy, ig], ...], "source", "updatedAt"}
Read at most once an hour; writes the file only when the data changed.
"""
import csv
import io
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "oas.json"
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2,BAMLC0A0CM&cosd={d}"
EVERY = timedelta(hours=1)


def main():
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    now = datetime.now(timezone.utc)
    if "--force" not in sys.argv and old.get("checkedAt"):
        if now - datetime.fromisoformat(old["checkedAt"]) < EVERY:
            return
    r = requests.get(URL.format(d=(date.today() - timedelta(days=3 * 365)).isoformat()), timeout=(10, 60))
    r.raise_for_status()
    hist = []
    for row in csv.reader(io.StringIO(r.text)):
        if len(row) < 3 or not row[0][:1].isdigit():
            continue
        try:
            hist.append([row[0].replace("-", ""), float(row[1]), float(row[2])])
        except ValueError:  # "." on holidays, or one of the two missing
            continue
    if len(hist) < 2:
        sys.exit("oas: no rows")
    hist.sort()
    a, b = hist[-1], hist[-2]
    out = {"date": f"{a[0][:4]}-{a[0][4:6]}-{a[0][6:]}", "hy": a[1], "ig": a[2], "hy_d1": b[1], "ig_d1": b[2],
           "source": "FRED: ICE BofA US High Yield / US Corporate Index Option-Adjusted Spread (BAMLH0A0HYM2, BAMLC0A0CM)",
           "hist": hist}
    same = {k: v for k, v in old.items() if k not in ("updatedAt", "checkedAt")} == out
    out["updatedAt"] = old.get("updatedAt") if same and old.get("updatedAt") else now.strftime("%Y-%m-%dT%H:%M:%SZ")
    out["checkedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    if not same:
        print(out["date"], out["hy"], out["ig"])


if __name__ == "__main__":
    main()
