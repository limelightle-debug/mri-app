"""S&P 500 daily lows and closes since 1990 (data/spx_daily.json) for the VIX app's event notes, whose table
carries the index's low each day of an event (as the institute's workbook does).
The history is filled once with yfinance (`--backfill`; Yahoo refuses plain requests from GitHub's runners); after
that each run takes the day's low and last from CNBC's quote for .SPX and puts it on the latest row (ET date).
Reads at most every 30 minutes (`--force` reads now); writes only when the series changed.
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


def yf_hist():
    import yfinance as yf  # only for the backfill
    df = yf.download("^GSPC", start="1990-01-01", auto_adjust=False, progress=False)
    lo, cl = df["Low"], df["Close"]
    if hasattr(lo, "columns"):
        lo, cl = lo.iloc[:, 0], cl.iloc[:, 0]
    return {t.strftime("%Y%m%d"): [round(float(a), 2), round(float(b), 2)] for t, a, b in zip(df.index, lo, cl)
            if a == a and b == b}


def cnbc_today():
    url = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=.SPX"
           "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")
    q = requests.get(url, headers={"User-Agent": UA}, timeout=40).json()["FormattedQuoteResult"]["FormattedQuote"][0]
    num = lambda x: float(str(x).replace(",", ""))
    t = q.get("last_time") or ""
    d = t[:10].replace("-", "")
    return d, [round(num(q["low"]), 2), round(num(q["last"]), 2)]


def main(force=False, backfill=False):
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if not backfill and old.get("hist"):
        if not force and old.get("checkedAt") and time.time() - datetime.fromisoformat(
                old["checkedAt"].replace("Z", "+00:00")).timestamp() < 1800:
            return
        try:
            d, v = cnbc_today()
        except Exception as e:  # noqa: BLE001
            sys.exit(f"spx_daily: CNBC: {type(e).__name__}: {e}")
        if not d.isdigit() or len(d) != 8:
            sys.exit(f"spx_daily: CNBC: no date ({d})")
        hist = [r for r in old["hist"] if r[0] != int(d)] + [[int(d)] + v]
        hist.sort()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out = {**old, "checkedAt": now, "hist": hist}
        if hist != old["hist"]:
            out["updatedAt"] = now
        OUT.write_text(json.dumps(out, separators=(",", ":")))
        return
    got, src, errs = None, None, []
    for name, fn in (("yfinance", yf_hist), ("Yahoo", yahoo), ("stooq", stooq)):
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
    main(force="--force" in sys.argv, backfill="--backfill" in sys.argv)
