"""Daily closes of the last few weeks for the paper's Sunday edition (the week's moves): data/weekly.json.

The five major indices, the 10-year Treasury yield, gold, WTI, the dollar against the yen and bitcoin, from CNBC's
chart service (one-year chart, daily bars; the last 30 kept). The chart leaves out the latest session for a while, so
the day's close is added from this repo's indices.json (the five indices) and markets.json (the rest). The app takes each week's change from the last close
of the week before. Reads at most every 3 hours; writes only when a series changed.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "weekly.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# key, CNBC symbol, ja
ITEMS = [
    ("SPX", ".SPX", "S&P500"), ("NDX", ".NDX", "ナスダック100"), ("DJI", ".DJI", "ダウ平均"),
    ("RUT", ".RUT", "ラッセル2000"), ("SOX", ".SOX", "半導体指数"),
    ("us10y", "US10Y", "米10年債"), ("gold", "@GC.1", "金"), ("wti", "@CL.1", "原油（WTI）"),
    ("usdjpy", "JPY=", "ドル円"), ("btc", "BTC.CM=", "ビットコイン"),
]
NY = ZoneInfo("America/New_York")


def bars(sym):
    r = requests.get(f"https://ts-api.cnbc.com/harmony/app/charts/1Y.json?symbol={sym}", headers={"User-Agent": UA},
                     timeout=40)
    r.raise_for_status()
    out = {}
    for b in r.json()["barData"]["priceBars"]:
        t = datetime.fromtimestamp(int(b["tradeTimeinMills"]) / 1000, timezone.utc).astimezone(NY)
        out[t.strftime("%Y%m%d")] = float(b["close"])
    return [[d, out[d]] for d in sorted(out)][-30:]


DATA = OUT.parent


def latest():
    """{key: (YYYYMMDD, close)} from indices.json's daily closes and markets.json's quotes (US Eastern date)."""
    out = {}
    try:
        idx = json.loads((DATA / "indices.json").read_text())
        for k, h in (idx.get("hist") or {}).items():
            final = {x["k"]: x for x in idx.get("indices", [])}.get(k)
            for d in sorted(h):
                # the last day only when that session is over (final)
                if d == max(h) and final and not final.get("final"):
                    continue
                out.setdefault(k, {})[d] = float(h[d])
    except (OSError, ValueError):
        pass
    try:
        mk = json.loads((DATA / "markets.json").read_text())
        for x in mk.get("items", []):
            t = str(x.get("time") or "")
            if x.get("price") is not None and len(t) >= 10:
                out.setdefault(x["k"], {})[t[:10].replace("-", "")] = float(x["price"])
    except (OSError, ValueError):
        pass
    return out


def main(force=False):
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if not force and old.get("checkedAt") and time.time() - datetime.fromisoformat(
            old["checkedAt"].replace("Z", "+00:00")).timestamp() < 3 * 3600:
        return
    items, errs, lat = {}, [], latest()
    for k, sym, ja in ITEMS:
        try:
            b = dict(bars(sym))
            b.update(lat.get(k, {}))
            # weekdays only (bitcoin trades on weekends too; its weekend is in weekend.json)
            b = [[d, b[d]] for d in sorted(b) if datetime.strptime(d, "%Y%m%d").weekday() < 5][-30:]
            if len(b) < 10:
                raise ValueError(f"only {len(b)} bars")
            items[k] = {"ja": ja, "d": b}
        except Exception as e:  # noqa: BLE001
            errs.append(f"{k}: {type(e).__name__}: {e}")
            if k in old.get("items", {}):
                items[k] = old["items"][k]
    if not items:
        sys.exit("weekly: " + "; ".join(errs))
    if errs:
        print(*errs, sep="\n", file=sys.stderr)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    same = old.get("items") == items
    OUT.write_text(json.dumps({"updatedAt": old.get("updatedAt", now) if same else now, "checkedAt": now,
                               "items": items}, ensure_ascii=False, separators=(",", ":")))
    if not same:
        print({k: v["d"][-1] for k, v in items.items()})


if __name__ == "__main__":
    main("--force" in sys.argv)
