"""Major US indices and the S&P 500 sector ETFs for the institute's morning paper: data/indices.json.

Each item tries its sources in turn (Cboe's delayed quotes first, then Nasdaq.com) and keeps the first
that answers. Writes the file only when a value changed, so runs while the market is closed make no commits.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "indices.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
NASDAQ_H = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}

# key, name (ja, en), sources: ("cboe", symbol, scale) or ("nasdaq", symbol, assetclass, scale)
INDICES = [
    ("SPX", "S&P500", "S&P 500", [("cboe", "_SPX", 1), ("nasdaq", "SPX", "index", 1)]),
    ("NDX", "ナスダック100", "Nasdaq 100", [("cboe", "_NDX", 1), ("nasdaq", "NDX", "index", 1)]),
    ("DJI", "ダウ平均", "Dow Jones", [("cboe", "_DJX", 100), ("nasdaq", "DJIA", "index", 1), ("nasdaq", "INDU", "index", 1)]),
    ("RUT", "ラッセル2000", "Russell 2000", [("cboe", "_RUT", 1), ("nasdaq", "RUT", "index", 1)]),
    ("SOX", "半導体指数", "Semiconductors (SOX)", [("nasdaq", "SOX", "index", 1), ("cboe", "_SOX", 1)]),
]
SECTORS = [
    ("XLK", "テクノロジー", "Technology"), ("XLC", "通信サービス", "Communication Services"),
    ("XLY", "一般消費財", "Consumer Discretionary"), ("XLP", "生活必需品", "Consumer Staples"),
    ("XLV", "ヘルスケア", "Health Care"), ("XLF", "金融", "Financials"), ("XLI", "資本財", "Industrials"),
    ("XLE", "エネルギー", "Energy"), ("XLB", "素材", "Materials"), ("XLU", "公益", "Utilities"),
    ("XLRE", "不動産", "Real Estate"),
]


def num(x):
    return float(str(x).replace("$", "").replace(",", "").replace("%", "").strip())


def cboe(sym, scale=1):
    r = requests.get(f"https://cdn.cboe.com/api/global/delayed_quotes/quotes/{sym}.json?_={int(time.time())}",
                     headers={"User-Agent": UA, "Cache-Control": "no-cache"}, timeout=30)
    r.raise_for_status()
    q = r.json().get("data") or {}
    price, prev = q.get("current_price") or q.get("close"), q.get("prev_day_close")
    if not price or not prev:
        raise ValueError(f"no price in {sym}: {sorted(q)[:12]}")
    return {"price": round(float(price) * scale, 2), "prev": round(float(prev) * scale, 2),
            "time": q.get("last_trade_time")}


def nasdaq(sym, cls, scale=1):
    r = requests.get(f"https://api.nasdaq.com/api/quote/{sym}/info?assetclass={cls}", headers=NASDAQ_H, timeout=30)
    r.raise_for_status()
    d = r.json().get("data") or {}
    p = d.get("primaryData") or {}
    if not p.get("lastSalePrice"):
        raise ValueError(f"no price for {sym}")
    price = num(p["lastSalePrice"])
    chg = num(p.get("netChange") or 0) if str(p.get("netChange") or "").strip() not in ("", "N/A", "UNCH") else 0.0
    return {"price": round(price * scale, 2), "prev": round((price - chg) * scale, 2), "time": p.get("lastTradeTimestamp")}


def fetch(sources):
    errs = []
    for s in sources:
        try:
            q = cboe(s[1], s[2]) if s[0] == "cboe" else nasdaq(s[1], s[2], s[3])
            q["src"] = f"{s[0]}:{s[1]}"
            q["pct"] = round((q["price"] / q["prev"] - 1) * 100, 2) if q["prev"] else None
            return q, errs
        except Exception as e:  # noqa: BLE001  (one bad source must not stop the rest)
            errs.append(f"{s[0]}:{s[1]}: {e}"[:160])
    return None, errs


def qday(t):
    """yyyymmdd of a quote's trade time: Cboe "2026-10-27T16:14:59" or Nasdaq "Oct 27, 2026 ..."."""
    t = str(t or "")
    try:
        return int(t[:10].replace("-", "")) if t[:4].isdigit() else int(datetime.strptime(" ".join(t.split()[:3]), "%b %d, %Y").strftime("%Y%m%d"))
    except ValueError:
        return None


def settle(q, k, hist, old_items):
    """Change against our own record of the previous session's close.

    Cboe rolls prev_day_close to the latest close some hours after the session (both then read the same),
    so the source's previous close is trusted only when it differs from the price."""
    day = qday(q.get("time"))
    h = hist.setdefault(k, {})
    # a session's close is fixed once taken after the session: later quotes (after hours, or the source
    # rolling its previous close overnight) never change it
    oldq = old_items.get(k)
    if day and oldq and oldq.get("final") and qday(oldq.get("time")) == day:
        return oldq
    now = datetime.now(ZoneInfo("America/New_York"))
    nowd = int(now.strftime("%Y%m%d"))
    q["final"] = bool(day) and (nowd > day or now.hour * 60 + now.minute >= 16 * 60 + 15)
    if day:
        before = [int(d) for d in h if int(d) < day]
        if before:
            q["prev"] = h[str(max(before))]
        elif abs(q["prev"] - q["price"]) < 1e-9 and oldq and qday(oldq.get("time")) == day and oldq.get("prev"):
            q["prev"] = oldq["prev"]
        h[str(day)] = q["price"]
        for d in sorted(h)[:-10]:
            del h[d]
    q["pct"] = round((q["price"] / q["prev"] - 1) * 100, 2) if q.get("prev") else None
    return q


def main():
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    hist = old.get("hist", {})
    old_items = {x["k"]: x for x in old.get("indices", []) + old.get("sectors", [])}
    out = {"indices": [], "sectors": [], "errors": []}
    for k, ja, en, src in INDICES:
        q, errs = fetch(src)
        out["errors"] += errs
        if q:
            out["indices"].append({"k": k, "ja": ja, "en": en, **settle(q, k, hist, old_items)})
    for t, ja, en in SECTORS:
        q, errs = fetch([("cboe", t, 1), ("nasdaq", t, "etf", 1)])
        out["errors"] += errs
        if q:
            out["sectors"].append({"k": t, "ja": ja, "en": en, **settle(q, t, hist, old_items)})
    if not out["indices"] and not out["sectors"]:
        print("no data:", *out["errors"], sep="\n", file=sys.stderr)
        sys.exit(1)
    # keep an item that failed this time from the last good file
    for part in ("indices", "sectors"):
        have = {x["k"] for x in out[part]}
        out[part] += [x for x in old.get(part, []) if x["k"] not in have]
    out["hist"] = hist
    same = all(old.get(p) == out[p] for p in ("indices", "sectors", "hist"))
    if same and old:
        return
    out["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    for x in out["indices"]:
        print(x["k"], x["price"], x["pct"], x["src"], x["time"])


if __name__ == "__main__":
    main()
