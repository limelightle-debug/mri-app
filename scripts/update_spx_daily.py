"""S&P 500 daily lows and closes since 1990 (data/spx_daily.json) for the VIX app's event notes, whose table
carries the index's low each day of an event (as the institute's workbook does). Yahoo's chart service; stooq
if it fails. Reads at most every 3 hours (`--force` reads now); writes only when the series changed.
"""
import csv
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "spx_daily.json"
NY = ZoneInfo("America/New_York")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def yahoo():
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?period1=631152000&period2={int(time.time())}"
           "&interval=1d&includePrePost=false")
    r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = {}
    for t, lo, c in zip(res["timestamp"], q["low"], q["close"]):
        if lo is None or c is None:
            continue
        d = datetime.fromtimestamp(t, NY).strftime("%Y%m%d")
        out[d] = [round(lo, 2), round(c, 2)]
    return out


def stooq():
    r = requests.get("https://stooq.com/q/d/l/?s=%5Espx&i=d", headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    out = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        try:
            if row["Date"] >= "1990-01-01":
                out[row["Date"].replace("-", "")] = [round(float(row["Low"]), 2), round(float(row["Close"]), 2)]
        except (KeyError, ValueError):
            continue
    return out


def main(force=False):
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if not force and old.get("checkedAt") and time.time() - datetime.fromisoformat(
            old["checkedAt"].replace("Z", "+00:00")).timestamp() < 3 * 3600:
        return
    got, src, errs = None, None, []
    for name, fn in (("Yahoo", yahoo), ("stooq", stooq)):
        try:
            d = fn()
            if len(d) >= 5000:
                got, src = d, name
                break
            errs.append(f"{name}: only {len(d)} days")
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name}: {type(e).__name__}: {e}")
    if not got:
        sys.exit("spx_daily: " + "; ".join(errs))
    hist = [[int(k)] + got[k] for k in sorted(got)]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {"updatedAt": old.get("updatedAt", now) if old.get("hist") == hist else now, "checkedAt": now,
           "source": src, "cols": ["date", "low", "close"], "hist": hist}
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(src, len(hist), hist[-1])


if __name__ == "__main__":
    main(force="--force" in sys.argv)
