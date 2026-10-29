"""Policy rate probabilities from 30-day fed funds futures, worked out the way CME's FedWatch does: data/fedwatch.json.

CME's own pages refuse automated reads, so the futures come from CNBC's quote service (@FF.1, @FF.2, ... the
contracts by month) and the current target range from the New York Fed (EFFR). For each FOMC meeting:
  - a contract's price P implies an average rate 100 - P for its month;
  - the rate after the meeting (in effect from the day after the decision) is the next month's implied rate when no
    meeting falls in that month; otherwise it is solved from the meeting month's average, given the rate before:
    avg = before * d1/N + after * (N - d1)/N, with d1 the days up to and including the decision day;
  - the rate before is the previous meeting's rate after (the first meeting: the month before's implied rate).
The expected number of 25bp moves since now, (after - now) / 0.25, is split between the two ranges around it (the
"aggregated" view). A snapshot per day is kept for the trend.
"""
import json
import sys
from calendar import monthrange
from datetime import date, datetime, timezone
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "fedwatch.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# FOMC decision days (the second day of each meeting)
FOMC = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
        "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08"]
CODES = "FGHJKMNQUVXZ"


def futures():
    syms = "|".join(f"@FF.{i}" for i in range(1, 19))
    r = requests.get("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol",
                     params={"symbols": syms, "requestMethod": "itv", "noform": "1", "partnerId": "2", "fund": "1",
                             "exthrs": "1", "output": "json"}, headers={"User-Agent": UA}, timeout=40)
    r.raise_for_status()
    out = {}
    for q in r.json()["FormattedQuoteResult"]["FormattedQuote"]:
        alt, last = q.get("altSymbol") or "", q.get("last") or q.get("previous_day_closing")
        if len(alt) == 5 and alt.startswith("FF") and last:
            ym = (2000 + int(alt[3:]), CODES.index(alt[2]) + 1)
            out[ym] = {"p": float(str(last).replace(",", "")), "settle": q.get("settlePrice"), "time": q.get("last_time")}
    if len(out) < 4:
        raise ValueError(f"fed funds futures: only {sorted(out)}")
    return out


def target():
    r = requests.get("https://markets.newyorkfed.org/api/rates/unsecured/effr/last/1.json", headers={"User-Agent": UA},
                     timeout=30)
    r.raise_for_status()
    x = r.json()["refRates"][0]
    return float(x["targetRateFrom"]), float(x["targetRateTo"]), float(x["percentRate"]), x["effectiveDate"]


def compute(F, lo, hi):
    meet = {}
    for s in FOMC:
        d = date.fromisoformat(s)
        meet[(d.year, d.month)] = d
    today = date.today()
    upcoming = [date.fromisoformat(s) for s in FOMC if date.fromisoformat(s) >= today]
    rate = lambda ym: 100 - F[ym]["p"] if ym in F else None
    prev = lambda ym: (ym[0] - (ym[1] == 1), 12 if ym[1] == 1 else ym[1] - 1)
    nxt = lambda ym: (ym[0] + (ym[1] == 12), 1 if ym[1] == 12 else ym[1] + 1)
    if not upcoming:
        return None
    first = (upcoming[0].year, upcoming[0].month)
    now = rate(prev(first)) if prev(first) not in meet and rate(prev(first)) is not None else None
    if now is None:
        raise ValueError("no month without a meeting before the next one")
    before, rows = now, []
    for d in upcoming:
        ym = (d.year, d.month)
        if ym not in F:
            break
        N, d1 = monthrange(*ym)[1], d.day
        after = rate(nxt(ym)) if nxt(ym) not in meet and rate(nxt(ym)) is not None else (rate(ym) - before * d1 / N) / ((N - d1) / N)
        k = (after - now) / 0.25  # 25bp moves expected since now
        f = int(k // 1)
        frac = k - f
        probs = {}
        for steps, pr in ((f, 1 - frac), (f + 1, frac)):
            if pr > 0.0005:
                a = lo + 0.25 * steps
                probs[f"{a:.2f}-{a + 0.25:.2f}"] = round(pr * 100, 1)
        rows.append({"date": d.isoformat(), "before": round(before, 4), "after": round(after, 4), "moves": round(k, 3),
                     "probs": probs})
        before = after
    return {"now": round(now, 4), "meetings": rows}


def main():
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    F = futures()
    lo, hi, effr, effr_day = target()
    res = compute(F, lo, hi)
    if not res:
        sys.exit("no upcoming meetings in the schedule")
    out = {"target": [lo, hi], "effr": effr, "effrDate": effr_day,
           "futures": {f"{y}-{m:02d}": v["p"] for (y, m), v in sorted(F.items())},
           "asof": max((v["time"] or "") for v in F.values()), **res}
    # one snapshot a day (US date of the quotes): expected moves at each of the next four meetings
    day = (out["asof"] or "")[:10] or date.today().isoformat()
    hist = [h for h in old.get("hist", []) if h[0] != day]
    hist.append([day] + [m["moves"] for m in res["meetings"][:4]] + [res["meetings"][0]["date"]])
    out["hist"] = sorted(hist)[-400:]
    if {k: v for k, v in old.items() if k != "updatedAt"} == out:
        return
    out["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    m = res["meetings"][0]
    print(m["date"], m["probs"], "futures", sorted(out["futures"]))


if __name__ == "__main__":
    main()
