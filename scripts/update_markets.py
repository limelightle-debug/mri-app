"""Commodities, Treasury yields and the yen for the institute's morning paper: data/markets.json.

One request to CNBC's quote service. Futures reopen at 18:00 ET, so the file keeps the snapshot taken
between 9:30 and 18:00 ET on weekdays (after 18:00 the quotes are the next session's); bitcoin trades
around the clock and is taken at the same moment. Writes only when a value changed.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "markets.json"
NY = ZoneInfo("America/New_York")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# key, CNBC symbol, ja, en, unit, decimals
ITEMS = [
    ("gold", "@GC.1", "金", "Gold", "ドル", 1),
    ("wti", "@CL.1", "原油（WTI）", "WTI crude", "ドル", 2),
    ("copper", "@HG.1", "銅", "Copper", "ドル", 3),
    ("btc", "BTC.CM=", "ビットコイン", "Bitcoin", "ドル", 0),
    ("us10y", "US10Y", "米10年債", "US 10Y", "%", 3),
    ("us2y", "US2Y", "米2年債", "US 2Y", "%", 3),
    ("usdjpy", "JPY=", "ドル円", "USD/JPY", "円", 2),
]
URL = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols={}"
       "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")


def num(x):
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def main(force=False):
    now = datetime.now(NY)
    m = now.hour * 60 + now.minute
    if not force and OUT.exists() and (now.weekday() >= 5 or not (9 * 60 + 30 <= m < 18 * 60)):
        return  # keep the close; outside the session window the futures quote the next session
    r = requests.get(URL.format("|".join(s for _, s, *_ in ITEMS)), headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    quotes = {q.get("symbol"): q for q in r.json()["FormattedQuoteResult"]["FormattedQuote"]}
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    keep = {x["k"]: x for x in old.get("items", [])}
    items = []
    for k, sym, ja, en, unit, dec in ITEMS:
        q = quotes.get(sym) or {}
        last, prev = num(q.get("last")), num(q.get("previous_day_closing"))
        if last is None:
            if k in keep:
                items.append(keep[k])
            continue
        chg = num(q.get("change"))
        if chg is None and prev:
            chg = last - prev
        pct = num(q.get("change_pct"))
        if pct is None and prev:
            pct = (last / prev - 1) * 100
        items.append({"k": k, "ja": ja, "en": en, "unit": unit, "dec": dec, "price": round(last, 4),
                      "chg": None if chg is None else round(chg, 4), "pct": None if pct is None else round(pct, 2),
                      "name": q.get("shortName") or q.get("name"), "time": q.get("last_time")})
    if not items:
        print("no quotes", file=sys.stderr)
        sys.exit(1)
    if old.get("items") == items:
        return
    OUT.write_text(json.dumps({"items": items, "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                              ensure_ascii=False, separators=(",", ":")))
    for x in items:
        print(x["k"], x["price"], x["chg"], x["pct"], x["time"])


if __name__ == "__main__":
    main(force="--force" in sys.argv)
