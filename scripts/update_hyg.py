"""HYG (iShares iBoxx $ High Yield Corporate Bond ETF) daily closes for five years: data/hyg.json, for the paper's
canary panel (the junk bond ETF's price beside the high yield spread): daily for the last year, weekly before. The price is the ETF's own (distributions
are paid out monthly, so it drifts lower than a total return would). CNBC's chart service first, stooq if it fails.
Reads at most every 3 hours (the closes change once a day); writes only when the series changed.
"""
import csv
import io
import json
import sys
import time
from datetime import datetime, timezone

import requests
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "hyg.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def cnbc_bars(span):
    r = requests.get(f"https://ts-api.cnbc.com/harmony/app/charts/{span}.json?symbol=HYG", headers={"User-Agent": UA},
                     timeout=40)
    r.raise_for_status()
    out = {}
    for b in r.json()["barData"]["priceBars"]:
        t = datetime.fromtimestamp(int(b["tradeTimeinMills"]) / 1000, timezone.utc)
        out[t.strftime("%Y%m%d")] = round(float(b["close"]), 2)
    return out


def cnbc():
    # the five-year chart comes in weekly bars, the one-year chart in daily ones: weekly before the last year
    wk, dy = cnbc_bars("5Y"), cnbc_bars("1Y")
    if len(dy) < 200:
        raise RuntimeError(f"1Y: only {len(dy)} days")
    first = min(dy)
    return {**{k: v for k, v in wk.items() if k < first}, **dy}


def stooq():
    r = requests.get("https://stooq.com/q/d/l/?s=hyg.us&i=d", headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    out = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        try:
            out[row["Date"].replace("-", "")] = round(float(row["Close"]), 2)
        except (KeyError, ValueError):
            continue
    return out


def main(force=False):
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if not force and old.get("checkedAt") and time.time() - datetime.fromisoformat(
            old["checkedAt"].replace("Z", "+00:00")).timestamp() < 3 * 3600:
        return
    got, src, errs = None, None, []
    for name, fn in (("CNBC", cnbc), ("stooq", stooq)):
        try:
            d = fn()
            if len(d) >= 400:
                got, src = d, name
                break
            errs.append(f"{name}: only {len(d)} days")
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name}: {type(e).__name__}: {e}")
    if not got:
        sys.exit("hyg: " + "; ".join(errs))
    keys = sorted(got)
    cut = str(int(keys[-1][:4]) - 5) + keys[-1][4:]
    hist = [[k, got[k]] for k in keys if k >= cut]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {"updatedAt": old.get("updatedAt", now) if old.get("hist") == hist else now, "checkedAt": now,
           "source": src, "hist": hist}
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(src, len(hist), hist[-1])


if __name__ == "__main__":
    main(force="--force" in sys.argv)
