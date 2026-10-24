"""Build data/vix.json for the VIX app: monthly VIX highs and lows, their +-sigma thresholds and the
VIX events.

Method (as in 恐怖指数研究所's workbook, VIX sheet):
  Each month's high (and low) is the highest (lowest) daily value of the month. Take log10. For a
  month, the mean and standard deviation (STDEV, n-1) cover the latest 360 months including that
  month; months before December 2019 (the first with 360 months of data) use the statistics of
  January 1990 to December 2019. Thresholds are 10^(mean + k * sd).
  A VIX event is the first month whose high exceeds +2 sigma; months above +2 sigma within 3 months
  of the previous one belong to the same event.

The current month uses Cboe's delayed quote for today (regular session) on top of the history file.
Sources: Cboe (VIX daily history, delayed quote). Runs in GitHub Actions with the MRI update.
"""
import csv
import io
import json
import math
import statistics as st
import sys
from datetime import datetime, timezone
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
WINDOW, FIXED_UNTIL, K_EVENT, GAP = 360, 201912, 2, 3


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
        try:
            m, d, y = row["DATE"].split("/")
            c = float(row["CLOSE"])
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
    """Today's regular-session values from Cboe's delayed quote: (yyyymmdd, [o, h, l, price], time)."""
    q = get(QUOTE).json().get("data") or {}
    try:
        t = datetime.fromisoformat(str(q["last_trade_time"])).replace(tzinfo=NY)
        vals = [float(q[k]) for k in ("open", "high", "low")] + [float(q.get("current_price") or q["close"])]
    except (KeyError, TypeError, ValueError):
        return None
    if min(vals) <= 0:
        return None
    return t.year * 10000 + t.month * 100 + t.day, vals, t.strftime("%Y-%m-%d %H:%M")


def main():
    days = history()
    lv = None
    try:
        lv = live()
    except (requests.RequestException, ValueError) as e:
        print(f"warning: live: {e}", file=sys.stderr)
    if lv:
        d, vals, _ = lv
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
            months[m] = [h, lo, c, d]
        else:
            r = months[m]
            r[0], r[1], r[2], r[3] = max(r[0], h), min(r[1], lo), c, d
    keys = sorted(months)
    lh = [math.log10(months[m][0]) for m in keys]
    ll = [math.log10(months[m][1]) for m in keys]
    i0 = keys.index(FIXED_UNTIL)
    rows, events, last = [], [], -99
    for i, m in enumerate(keys):
        j = max(i, i0)
        wh, wl = lh[j - WINDOW + 1:j + 1], ll[j - WINDOW + 1:j + 1]
        mh, sh, ml, sl = st.mean(wh), st.stdev(wh), st.mean(wl), st.stdev(wl)
        h, lo, c, lastday = months[m]
        rows.append([m, h, lo, c, round(mh, 6), round(sh, 6), round(ml, 6), round(sl, 6)])
        if h > 10 ** (mh + K_EVENT * sh):
            if i - last > GAP:
                events.append(m)
            last = i
    # details per event: the first day above +2 sigma, the peak of the episode, the S&P 500's fall
    info = {}
    try:
        spx = spx_closes()
    except Exception as e:  # noqa: BLE001
        print(f"warning: spx: {e}", file=sys.stderr)
        spx = {}
    thr = {r[0]: 10 ** (r[4] + K_EVENT * r[5]) for r in rows}
    for m in events:
        i0 = keys.index(m)
        last_i, pk = i0, m
        for i in range(i0 + 1, len(keys)):
            if i - last_i > GAP:
                break
            if months[keys[i]][0] > thr[keys[i]]:
                last_i = i
                if months[keys[i]][0] > months[pk][0]:
                    pk = keys[i]
        first = next(d for d in sorted(days) if d // 100 == m and days[d][1] > thr[m])
        peak_day = max((d for d in days if d // 100 == pk), key=lambda d: days[d][1])
        e = {"day": first, "peakDay": peak_day, "peak": days[peak_day][1], "last": keys[last_i]}
        if spx:
            lo_from, lo_to = add_months(m, -1) * 100, add_months(keys[last_i], 3) * 100 + 31
            win = [d for d in spx if lo_from <= d <= lo_to]
            if win:
                trough = min(win, key=lambda d: spx[d])
                pk_from = add_months(trough // 100, -6) * 100 + trough % 100
                top = max((d for d in spx if pk_from <= d <= trough), key=lambda d: spx[d])
                fall = 1 - spx[trough] / spx[top]
                e.update({"spxTop": top, "spxTrough": trough, "fall": round(fall, 4),
                          "shindo": next(lv for th, lv in SHINDO if fall >= th)})
        info[str(m)] = e
    lastday = max(days)
    data = {
        "source": "Cboe",
        "method": {"window": WINDOW, "fixedUntil": FIXED_UNTIL, "event": K_EVENT, "gap": GAP, "log10": True},
        "lastDay": lastday,
        "live": {"date": lv[0], "time": lv[2], "price": lv[1][3], "high": lv[1][1], "low": lv[1][2]} if lv else None,
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
