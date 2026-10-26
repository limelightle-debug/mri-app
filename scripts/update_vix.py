"""Build data/vix.json for the VIX app: monthly VIX highs and lows, their +-sigma thresholds and the
VIX events.

Method (as in 恐怖指数研究所's workbook, VIX sheet):
  Each month's high (and low) is the highest (lowest) daily value of the month. Take log10. For a
  month, the mean and standard deviation (STDEV, n-1) cover the latest 360 months including that
  month; months before December 2019 (the first with 360 months of data) use the statistics of
  January 1990 to December 2019. Thresholds are 10^(mean + k * sd).
  A VIX event starts on the first day whose high exceeds +2 sigma as of the previous month and ends when
  the daily high fails to pass that +1 sigma (of the month before the start) for 10 days in a row.

The current month uses Cboe's delayed quote for today (regular session) on top of the history file.
Sources: Cboe (VIX daily history, delayed quote). Runs in GitHub Actions with the MRI update.
"""
import csv
import io
import json
import math
import statistics as st
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

NY = ZoneInfo("America/New_York")
DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "vix.json"
CACHE = DATA / "vix_history.csv"  # not committed; refreshed hourly
HIST = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
SPX_HIST = "https://cdn.cboe.com/api/global/us_indices/daily_prices/SPX_History.csv"
SPX_CACHE = DATA / "spx_history.csv"  # not committed; refreshed hourly
QUOTE = "https://cdn.cboe.com/api/global/delayed_quotes/quotes/_VIX.json"
WINDOW, FIXED_UNTIL, K_EVENT, GAP, END_DAYS = 360, 201912, 2, 3, 10


def get(url):
    r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r


def cached(url, path):
    fresh = path.exists() and (datetime.now().timestamp() - path.stat().st_mtime) < 3600
    if not fresh:
        try:
            path.write_text(get(url).text, encoding="utf-8")
        except requests.RequestException as e:
            if not path.exists():
                raise
            print(f"warning: {url}: {e}", file=sys.stderr)
    return path.read_text(encoding="utf-8")


def spx_closes():
    out = {}
    for row in csv.DictReader(io.StringIO(cached(SPX_HIST, SPX_CACHE))):
        row = {k.strip().upper(): v for k, v in row.items() if k}  # the header's case and spacing vary
        try:
            m, d, y = row["DATE"].split("/")
            c = float(str(row.get("CLOSE") or row.get("SPX")).replace(",", ""))
        except (KeyError, ValueError):
            continue
        if c > 0:
            out[int(y) * 10000 + int(m) * 100 + int(d)] = c
    return out


# the S&P 500's fall around an event, as the earthquake's intensity (shindo, JMA scale):
# trough = lowest close from a month before the event to 3 months after its last month above +2 sigma;
# peak = highest close in the 6 months before the trough
SHINDO = [(0.40, "7"), (0.30, "6+"), (0.20, "6-"), (0.15, "5+"), (0.10, "5-"), (0.05, "4"), (0.0, "3")]


def add_months(m, k):
    y, mo = divmod(m // 100 * 12 + m % 100 - 1 + k, 12)
    return y * 100 + mo + 1


def history():
    days = {}
    for row in csv.DictReader(io.StringIO(cached(HIST, CACHE))):
        try:
            m, d, y = row["DATE"].split("/")
            o, h, lo, c = (float(row[k]) for k in ("OPEN", "HIGH", "LOW", "CLOSE"))
        except (KeyError, ValueError):
            continue
        if h > 0 and lo > 0:
            days[int(y) * 10000 + int(m) * 100 + int(d)] = [o, h, lo, c]
    if len(days) < 5000:
        raise RuntimeError(f"VIX history: only {len(days)} days")
    return days


def live():
    """Cboe's delayed quote: (yyyymmdd, [o, h, l, c] of the regular session, its time, latest quote).

    Outside the regular session the quote keeps the last regular trade's time while its price follows
    the extended session (from 3:15 ET): then the latest price is stamped with the fetch time and
    compared with the regular close."""
    j = get(QUOTE).json()
    q = j.get("data") or {}
    try:
        t = datetime.fromisoformat(str(q["last_trade_time"])).replace(tzinfo=NY)
        o, h, lo = (float(q[k]) for k in ("open", "high", "low"))
        price = float(q.get("current_price") or q["close"])
        close = float(q.get("close") or price)
        prev = float(q.get("prev_day_close") or close)
        fetched = datetime.strptime(str(j.get("timestamp"))[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(NY)
    except (KeyError, TypeError, ValueError):
        return None
    if min(o, h, lo, price) <= 0:
        return None
    after_close = t.hour * 60 + t.minute >= 16 * 60
    fm = fetched.hour * 60 + fetched.minute
    extended = fetched.weekday() < 5 and 3 * 60 + 15 <= fm < 9 * 60 + 30
    if after_close and (abs(price - close) > 1e-9 or (extended and fetched.date() > t.date())):
        # the extended session: the regular day is over, the price is the overnight one
        quote = {"price": price, "prevClose": close, "time": fetched.strftime("%Y-%m-%d %H:%M"), "session": "extended"}
        reg = [o, h, lo, close]
    else:
        session = "regular" if not after_close else "closed"
        base = prev if session == "regular" else (prev if fetched.date() == t.date() else close)
        quote = {"price": price, "prevClose": base, "time": t.strftime("%Y-%m-%d %H:%M"), "session": session}
        reg = [o, h, lo, price]
    return t.year * 10000 + t.month * 100 + t.day, reg, t.strftime("%Y-%m-%d %H:%M"), quote


def main():
    days = history()
    lv = None
    try:
        lv = live()
    except (requests.RequestException, ValueError) as e:
        print(f"warning: live: {e}", file=sys.stderr)
    if lv:
        d, vals, _, _q = lv
        if d not in days:
            days[d] = vals
        else:  # the history may already have the day; keep the wider range
            o, h, lo, c = days[d]
            days[d] = [o, max(h, vals[1]), min(lo, vals[2]), c]
    months = {}
    for d in sorted(days):
        m = d // 100
        o, h, lo, c = days[d]
        if m not in months:
            months[m] = [h, lo, c, d, o]  # o: the month's first open
        else:
            r = months[m]
            r[0], r[1], r[2], r[3] = max(r[0], h), min(r[1], lo), c, d
    keys = sorted(months)
    lh = [math.log10(months[m][0]) for m in keys]
    lc = [math.log10(months[m][2]) for m in keys]
    ll = [math.log10(months[m][1]) for m in keys]
    i0 = keys.index(FIXED_UNTIL)
    rows, events, last = [], [], -99
    for i, m in enumerate(keys):
        j = max(i, i0)
        wh, wl = lh[j - WINDOW + 1:j + 1], ll[j - WINDOW + 1:j + 1]
        mh, sh, ml, sl = st.mean(wh), st.stdev(wh), st.mean(wl), st.stdev(wl)
        mc = st.mean(lc[j - WINDOW + 1:j + 1])  # the mean of the log of monthly closes (the candle chart's centre)
        # normal range (workbook AP41:AR41): the medians of the monthly lows and highs over the same window
        hs, ls = [months[k][0] for k in keys[j - WINDOW + 1:j + 1]], [months[k][1] for k in keys[j - WINDOW + 1:j + 1]]
        med_h, med_l = st.median(hs), st.median(ls)
        h, lo, c, lastday, o = months[m]
        rows.append([m, h, lo, c, round(mh, 6), round(sh, 6), round(ml, 6), round(sl, 6), o, round(mc, 6), round(med_l, 4), round(med_h, 4)])
    # events, daily, on the thresholds as of the previous month (as in the workbook's VIX Eve sheet, known when the
    # month begins): an event starts on the first day whose high passes +2σ, and ends on the 10th trading day in a
    # row whose high stays below the +1σ of the month before it started (it could not pass +1σ for 10 days)
    by_m = {r[0]: r for r in rows}
    pm = lambda m: by_m.get(add_months(m, -1), by_m[m])
    t1 = {m: 10 ** (pm(m)[4] + pm(m)[5]) for m in by_m}
    t2 = {m: 10 ** (pm(m)[4] + K_EVENT * pm(m)[5]) for m in by_m}
    dl = sorted(days)
    spans, k = [], 0
    while k < len(dl):
        d = dl[k]
        if days[d][1] > t2[d // 100]:
            run, end, lim = 0, None, t1[d // 100]
            for q in range(k + 1, len(dl)):
                run = run + 1 if days[dl[q]][1] < lim else 0
                if run == END_DAYS:
                    end = dl[q]
                    break
            spans.append((d, end))
            k = dl.index(end) + 1 if end else len(dl)
        else:
            k += 1
    events = [st_ // 100 for st_, _ in spans]
    # details per event: the first day above +2 sigma, the peak of the episode, the S&P 500's fall
    info = {}
    try:
        spx = spx_closes()
    except Exception as e:  # noqa: BLE001
        print(f"warning: spx: {e}", file=sys.stderr)
        spx = {}
    thr = {r[0]: 10 ** (r[4] + K_EVENT * r[5]) for r in rows}
    for (first, end) in spans:
        m = first // 100
        span_days = [d for d in dl if first <= d <= (end or dl[-1])]
        peak_day = max(span_days, key=lambda d: days[d][1])
        last_m = (end or dl[-1]) // 100
        e = {"day": first, "end": end, "peakDay": peak_day, "peak": days[peak_day][1], "last": last_m}
        if spx:
            lo_from, lo_to = add_months(m, -1) * 100, add_months(last_m, 1) * 100 + 31
            win = [d for d in spx if lo_from <= d <= lo_to]
            if win:
                trough = min(win, key=lambda d: spx[d])
                pk_from = add_months(trough // 100, -6) * 100 + trough % 100
                top = max((d for d in spx if pk_from <= d <= trough), key=lambda d: spx[d])
                fall = 1 - spx[trough] / spx[top]
                e.update({"spxTop": top, "spxTrough": trough, "fall": round(fall, 4),
                          "shindo": next(lv for th, lv in SHINDO if fall >= th)})
        info[str(m)] = e
    # the latest quote's change: from the previous day's close in the regular session (and after it), from the
    # regular close in the extended session
    quote = lv[3] if lv else None
    if quote and quote["session"] != "extended":
        before = [d for d in days if d < lv[0]]
        if before:
            quote["prevClose"] = days[max(before)][3]
    lastday = max(days)
    data = {
        "source": "Cboe",
        "method": {"window": WINDOW, "fixedUntil": FIXED_UNTIL, "event": K_EVENT, "gap": GAP, "log10": True},
        "lastDay": lastday,
        "live": {"date": lv[0], "time": lv[2], "price": lv[1][3], "high": lv[1][1], "low": lv[1][2]} if lv else None,
        "quote": quote,
        "months": rows,
        "events": events,
        "eventInfo": info,
    }
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    old.pop("updatedAt", None)
    if old == data:
        print("vix: no change")
        return
    OUT.write_text(json.dumps({"updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **data},
                              separators=(",", ":")), encoding="utf-8")
    print(f"vix: {len(rows)} months, last {keys[-1]} high {rows[-1][1]}, events {events}")


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
