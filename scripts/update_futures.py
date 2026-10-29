"""Stock index futures (and the commodity, dollar, yen and Treasury yield quotes) before the US open, for the evening edition of the institute's paper: data/futures.json.

One request to CNBC's quote service: the E-mini S&P 500, Nasdaq 100, Dow and Russell 2000 front contracts, and the
semiconductor ETF SOXX's pre-market quote (no SOX future trades). The change is against the previous session's
settlement (CNBC's change and change_pct). Read on weekdays from 4:00 to 9:35 ET, when the evening edition can use
it; the file keeps the last pre-open snapshot through the day. The quotes of markets.json's items (commodity
futures, the dollar, cross-yen rates, 2Y and 10Y yields, bitcoin) are taken in the same request, under "markets",
so the evening edition can show them as they stand before the open (markets.json keeps the regular session). Writes only when a value changed.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from update_markets import ITEMS as MKT, ETFS  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "futures.json"
NY = ZoneInfo("America/New_York")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# key (the same keys as indices.json), CNBC symbol, ja, en
ITEMS = [
    ("SPX", "@SP.1", "S&P500先物", "S&P 500 futures"),
    ("NDX", "@ND.1", "ナスダック100先物", "Nasdaq 100 futures"),
    ("DJI", "@DJ.1", "ダウ先物", "Dow futures"),
    ("RUT", "@RTY.1", "ラッセル2000先物", "Russell 2000 futures"),
    ("SOX", "SOXX", "半導体ETF（寄り前）", "Semiconductor ETF (pre-market)"),
]
URL = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols={}"
       "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")


def num(x):
    try:
        return float(str(x).replace(",", "").replace("%", "").replace("+", "").strip())
    except (TypeError, ValueError):
        return None


def main(force=False):
    now = datetime.now(NY)
    m = now.hour * 60 + now.minute
    if not force and not (now.weekday() < 5 and 4 * 60 <= m <= 9 * 60 + 35):
        return
    mk = [x for x in MKT if x[0] not in ETFS]
    r = requests.get(URL.format("|".join([x[1] for x in ITEMS] + [x[1] for x in mk])), headers={"User-Agent": UA},
                     timeout=40)
    r.raise_for_status()
    qs = r.json()["FormattedQuoteResult"]["FormattedQuote"]
    if "--dump" in sys.argv:
        print(json.dumps(qs, ensure_ascii=False, indent=1)[:12000], file=sys.stderr)
    by = {q.get("symbol"): q for q in qs}
    items = []
    for key, sym, ja, en in ITEMS:
        q = by.get(sym)
        if not q:
            continue
        last, chg, pct, t = num(q.get("last")), num(q.get("change")), num(q.get("change_pct")), q.get("last_time")
        ext = q.get("ExtendedMktQuote") or {}
        if key == "SOX" and ext.get("last"):  # the ETF's pre-market quote
            last, chg, pct, t = num(ext.get("last")), num(ext.get("change")), num(ext.get("change_pct")), ext.get("last_time")
        if last is None or pct is None:
            continue
        items.append({"key": key, "sym": sym, "alt": q.get("altSymbol"), "ja": ja, "en": en, "price": last,
                      "chg": chg, "pct": pct, "prev": num(q.get("previous_day_closing")), "time": t})
    if len(items) < 3:
        sys.exit(f"futures: only {[i['key'] for i in items]}")
    markets = {}
    for key, sym, ja, en, unit, dec in mk:
        q = by.get(sym)
        if q and num(q.get("last")) is not None:
            markets[key] = {"price": num(q.get("last")), "chg": num(q.get("change")), "pct": num(q.get("change_pct")),
                            "time": q.get("last_time")}
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if old.get("items") == items and old.get("markets") == markets:
        return
    out = {"updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "day": now.strftime("%Y-%m-%d"),
           "items": items, "markets": markets}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print({i["key"]: (i["price"], i["pct"], i["time"]) for i in items})


if __name__ == "__main__":
    main(force="--force" in sys.argv)
