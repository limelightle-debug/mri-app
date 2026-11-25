"""The S&P 500 from the inside, for the paper: data/spx_breadth.json.

How many of its stocks rose and fell, each GICS sector's move (weighted by the index weights), and the stocks that
added the most points to the index and took the most away.

Sources: the index weights from the daily holdings of SPDR SPY (which replicates the index), each stock's sector from
the daily holdings of the eleven SPDR sector funds (each holds one GICS sector of the S&P 500), both fetched once a
day and kept in data/spx_members.json; the prices from CNBC's quotes (50 stocks to a request).
"""
import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import openpyxl
import requests

DATA = Path(__file__).resolve().parent.parent / "data"
OUT, MEMBERS, INDICES = DATA / "spx_breadth.json", DATA / "spx_members.json", DATA / "indices.json"
NY = ZoneInfo("America/New_York")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SSGA = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{}.xlsx"
SECTORS = [
    ("XLK", "テクノロジー", "Technology"), ("XLC", "通信サービス", "Communication Services"),
    ("XLY", "一般消費財", "Consumer Discretionary"), ("XLP", "生活必需品", "Consumer Staples"),
    ("XLV", "ヘルスケア", "Health Care"), ("XLF", "金融", "Financials"), ("XLI", "資本財", "Industrials"),
    ("XLE", "エネルギー", "Energy"), ("XLB", "素材", "Materials"), ("XLU", "公益", "Utilities"),
    ("XLRE", "不動産", "Real Estate"),
]
CNBC = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols={}"
        "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")


def holdings(fund):
    """[(ticker, weight %), ...] and the date from a SPDR fund's daily holdings file."""
    r = requests.get(SSGA.format(fund.lower()), headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    ws = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True).active
    rows, head, asof = [], None, None
    for row in ws.iter_rows(values_only=True):
        if row and row[0] == "Holdings:" and row[1]:
            m = re.search(r"(\d{1,2}-[A-Za-z]{3}-\d{4})", str(row[1]))
            asof = datetime.strptime(m.group(1), "%d-%b-%Y").strftime("%Y-%m-%d") if m else None
        if head is None:
            if row and "Ticker" in row and "Weight" in row:
                head = {k: row.index(k) for k in ("Name", "Ticker", "Weight")}
            continue
        t, w = row[head["Ticker"]], row[head["Weight"]]
        if not t or not isinstance(w, (int, float)) or not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", str(t)):
            continue
        rows.append((str(t), float(w)))
    if not rows:
        raise RuntimeError(f"{fund}: no holdings")
    return rows, asof


def members(now):
    """The index weights and each stock's sector, refreshed once a day (kept when a fetch fails)."""
    old = json.loads(MEMBERS.read_text(encoding="utf-8")) if MEMBERS.exists() else {}
    if old.get("fetched") == str(now.date()) and old.get("w"):
        return old
    try:
        spy, asof = holdings("SPY")
        if len(spy) < 450:
            raise RuntimeError(f"SPY: only {len(spy)} stocks")
        sec = dict(old.get("sec") or {})
        for k, *_ in SECTORS:
            try:
                for t, _ in holdings(k)[0]:
                    sec[t] = k
            except Exception as e:  # noqa: BLE001  (the sector kept from before stays)
                print(f"warning: {k}: {e}"[:200], file=sys.stderr)
            time.sleep(1)
        tot = sum(w for _, w in spy)
        out = {"fetched": str(now.date()), "asOf": asof, "w": {t: round(w / tot * 100, 5) for t, w in spy},
               "sec": {t: sec[t] for t, _ in spy if t in sec}}
        MEMBERS.write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")
        return out
    except Exception as e:  # noqa: BLE001
        print(f"warning: members: {e}; keeping the last list", file=sys.stderr)
        if not old.get("w"):
            raise
        return old


def num(x):
    return float(str(x).replace(",", "").replace("%", "").replace("+", "").strip())


def quotes(tickers):
    out = {}
    for i in range(0, len(tickers), 50):
        try:
            r = requests.get(CNBC.format("|".join(tickers[i:i + 50])), headers={"User-Agent": UA}, timeout=30)
            r.raise_for_status()
            rows = ((r.json().get("FormattedQuoteResult") or {}).get("FormattedQuote")) or []
        except (requests.RequestException, ValueError) as e:
            print(f"warning: quotes {i}: {e}"[:200], file=sys.stderr)
            continue
        for q in rows:
            try:
                out[q["symbol"]] = {"last": num(q["last"]), "prev": num(q["previous_day_closing"]),
                                    "time": q.get("last_time"), "name": q.get("name") or q["symbol"]}
            except (KeyError, ValueError):
                continue
        time.sleep(0.5)
    return out


def short(name):
    """'Apple Inc.' -> 'Apple'; 'Eli Lilly and Company' -> 'Eli Lilly' (for a narrow list)."""
    s = re.sub(r" Class [A-Z]$", "", name.strip())
    for _ in range(2):
        s = re.sub(r",? (Inc\.?|Corp\.?|Corporation|Company|Co\.?|Ltd\.?|plc|Holdings?|Group|Incorporated|N\.V\.|S\.A\.|L\.P\.)$",
                   "", s.strip(" ,"), flags=re.I)
        s = re.sub(r"( and| &)$", "", s.strip(" ,"))
    s = re.sub(r"^The ", "", s)
    return s.strip(" ,") or name


def main():
    now = datetime.now(NY)
    m = members(now)
    W, S = m["w"], m["sec"]
    Q = quotes(sorted(W))
    if len(Q) < 450:
        sys.exit(f"only {len(Q)} quotes")
    spx = None
    try:
        spx = next(x for x in json.loads(INDICES.read_text(encoding="utf-8"))["indices"] if x["k"] == "SPX")
    except Exception:  # noqa: BLE001
        pass
    prev = spx.get("prev") if spx else None
    if not prev and spx and spx.get("pct") is not None:
        prev = spx["price"] / (1 + spx["pct"] / 100)
    up = dn = flat = 0
    sec = {k: [0.0, 0.0] for k, *_ in SECTORS}
    rows = []
    for t, w in W.items():
        q = Q.get(t)
        if not q or not q["prev"]:
            continue
        r = (q["last"] / q["prev"] - 1) * 100
        if r > 0.0001:
            up += 1
        elif r < -0.0001:
            dn += 1
        else:
            flat += 1
        k = S.get(t)
        if k in sec:
            sec[k][0] += w * r
            sec[k][1] += w
        pts = w / 100 * r / 100 * prev if prev else None
        rows.append([t, short(q["name"]), round(r, 2), round(pts, 2) if pts is not None else None, round(w * r / 100, 4)])
    rows.sort(key=lambda x: -x[4])
    times = sorted(q["time"] for q in Q.values() if q.get("time"))
    data = {
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "time": times[-1] if times else None, "weightsAsOf": m.get("asOf"), "n": up + dn + flat,
        "up": up, "down": dn, "flat": flat, "spxPrev": round(prev, 2) if prev else None,
        "sectors": [{"k": k, "ja": ja, "en": en, "w": round(sec[k][1], 2),
                     "pct": round(sec[k][0] / sec[k][1], 2) if sec[k][1] else None} for k, ja, en in SECTORS],
        # [ticker, name, change %, index points, contribution in % of the index]
        "top": [x for x in rows[:5] if x[4] > 0], "bottom": [x for x in rows[::-1][:5] if x[4] < 0],
        "sum": round(sum(x[4] for x in rows), 3),
    }
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    if {k: v for k, v in old.items() if k != "updatedAt"} == {k: v for k, v in data.items() if k != "updatedAt"}:
        print("no change")
        return
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"breadth: {up} up / {dn} down, sum {data['sum']}%, top {data['top'][:1]}")


if __name__ == "__main__":
    main()
