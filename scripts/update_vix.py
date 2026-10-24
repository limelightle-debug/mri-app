"""Build data/vix.json for the VIX app: monthly VIX highs and lows, their +-sigma thresholds and the
VIX events.

Method (as in 恐怖指数研究所's workbook, VIX sheet):
  Each month's high (and low) is the highest (lowest) daily value of the month. Take log10. For a
  month, the mean and standard deviation (STDEV, n-1) cover the latest 360 months including that
  month; months before December 2019 (the first with 360 months of data) use the statistics of
  January 1990 to December 2019. Thresholds are 10^(mean + k * sd).
  A VIX event starts on the first day whose high exceeds that month's +2 sigma and ends when the daily
  high fails to pass +1 sigma for 10 days in a row.

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
WINDOW, FIXED_UNTIL, K_EVENT, GAP, END_DAYS = 360, 201912, 2, 3, 10
BAYES_FROM, MRI_LINE, MRI_WIDTH = 201801, 75, 3


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


def bpt_cdf(t, mu, a):
    """Brownian Passage Time: the share of intervals shorter than t months (mean mu, aperiodicity a)."""
    if t <= 0:
        return 0.0
    phi = lambda z: .5 * (1 + math.erf(z / math.sqrt(2)))
    u1 = (math.sqrt(t / mu) - math.sqrt(mu / t)) / a
    u2 = (math.sqrt(t / mu) + math.sqrt(mu / t)) / a
    return phi(u1) + math.exp(2 / a ** 2) * phi(-u2)


def backtest(spans, mri, months):
    """The event probability as it would have read at the start of each month since the first event, two ways:
    "in" with parameters from all the data (the model as it stands, applied to the past) and "out" with only what
    was known then (intervals, frequency and the MRI factor from earlier events; until 3 intervals are known the
    interval part is random). MRI counts from 2018, when it works. Rows: [month, during an event (1/0), then
    in Bayes, in interval, in random, out Bayes, out interval, out random, each for 1, 3, 6 and 12 months, in %]."""
    import bisect
    md = sorted(mri)
    idx = lambda m: m // 100 * 12 + m % 100
    smon = [s_ // 100 for s_, _ in spans]
    def last_end(d):
        ends = [e for s_, e in spans if e and e < d]
        return max(ends) if ends else 0
    def xat(d):
        lo = max(last_end(d), add_months(d // 100, -6) * 100 + d % 100)
        vals = [mri[k] for k in md[bisect.bisect_right(md, lo):bisect.bisect_left(md, d)]]
        return max(vals) if vals else None
    in_event = lambda d: any(s_ <= d <= (e or 99999999) for s_, e in spans)
    mm = [m for m in months if m >= BAYES_FROM]
    X = {m: xat(m * 100 + 1) for m in mm}
    XE = {s_: xat(s_) for s_, _ in spans if s_ >= BAYES_FROM * 100}
    def mri_params(upto):
        xe = [x for s_, x in XE.items() if x is not None and (upto is None or s_ < upto * 100 + 1)]
        xn = [X[k] for k in mm if X[k] is not None and not in_event(k * 100 + 1) and (upto is None or k < upto)]
        if not xe or len(xn) < 6:
            return None
        pe = (sum(x >= MRI_LINE for x in xe) + 1) / (len(xe) + 2)
        pn = sum(x >= MRI_LINE for x in xn) / len(xn)
        if pn in (0, 1):
            return None
        return pe / pn, (1 - pe) / (1 - pn), pn
    def factors(x, par, upto):
        hi, lo, pn = par
        known = lambda k: upto is None or k < upto
        for band in (5, 8, 12, 100):
            base = [k for k in mm if X[k] is not None and abs(X[k] - x) <= band and not in_event(k * 100 + 1) and known(k)]
            if len(base) >= 20:
                break
        q = []
        for j in range(1, 13):
            fut = [X[add_months(k, j)] for k in base if X.get(add_months(k, j)) is not None and known(add_months(k, j))]
            q.append(sum(f >= MRI_LINE for f in fut) / len(fut) if len(fut) >= 3 else pn)
        return {k: st.mean(qq * hi + (1 - qq) * lo for qq in q[:k]) for k in (1, 3, 6, 12)}
    par_in = mri_params(None)
    iv_all = [idx(b) - idx(a) for a, b in zip(smon, smon[1:])]
    rows = []
    for m in months:
        if m <= smon[0]:
            continue
        d = m * 100 + 1
        ongoing = any(s_ < d and (e is None or e >= d) for s_, e in spans)
        prior = [s_ for s_ in smon if s_ < m]
        e = idx(m) - idx(prior[-1])
        row = [m, int(ongoing)]
        for mode in ("in", "out"):
            if mode == "in":
                iv, lam, par, upto = iv_all, len(smon) / len(months), par_in, None
            else:
                iv = [idx(b) - idx(a) for a, b in zip(prior, prior[1:])]
                lam, par, upto = len(prior) / (idx(m) - idx(months[0])), mri_params(m), m
            x = X.get(m)
            fk = factors(x, par, upto) if x is not None and par else {}
            post, bpt, base = [], [], []
            for k in (1, 3, 6, 12):
                b = 1 - math.exp(-lam * k)
                if len(iv) >= 3:
                    mu = st.mean(iv)
                    a = st.stdev(iv) / mu
                    p = (bpt_cdf(e + k, mu, a) - bpt_cdf(e, mu, a)) / (1 - bpt_cdf(e, mu, a))
                else:
                    p = b
                o = p / (1 - p) * fk.get(k, 1)
                post.append(0 if ongoing else o / (1 + o))
                bpt.append(0 if ongoing else p)
                base.append(b)
            row += [round(v * 100, 2) for v in post + bpt + base]
        rows.append(row)
    return rows


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
    # events, daily: an event starts on the first day whose high passes its month's +2σ, and ends on the 10th
    # trading day in a row whose high stays below its month's +1σ (it could not pass +1σ for 10 days)
    t1 = {r[0]: 10 ** (r[4] + r[5]) for r in rows}
    t2 = {r[0]: 10 ** (r[4] + K_EVENT * r[5]) for r in rows}
    dl = sorted(days)
    spans, k = [], 0
    while k < len(dl):
        d = dl[k]
        if days[d][1] > t2[d // 100]:
            run, end = 0, None
            for q in range(k + 1, len(dl)):
                run = run + 1 if days[dl[q]][1] < t1[dl[q] // 100] else 0
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
    # MRI as evidence (Bayes). x = the highest daily MRI over the last 6 months, or since the last event ended if that
    # is more recent (during an event there is no next event to forecast). Every event so far came with x at or above
    # the 75 line, but so did many quiet months: the line works as a step, not a slope. The likelihood ratio is
    # P(x >= 75 | before an event) / P(x >= 75 | other months) above the line and the same for below, the event share
    # smoothed by Laplace's rule, +1 / +2 (4 of 4 is not certainty), switching over a logistic of width 3 in the log odds.
    # Since 2018, when MRI works; other months are month starts outside events
    bayes = None
    try:
        mri = {r[0]: r[7] * 100 for r in json.loads((DATA / "mri.json").read_text(encoding="utf-8"))["daily"]}
        md = sorted(mri)
        def last_end(d):
            ends = [e for s_, e in spans if e and e < d]
            return max(ends) if ends else 0
        def xat(d, inclusive=False):
            lo = max(last_end(d), add_months(d // 100, -6) * 100 + d % 100)
            vals = [mri[k] for k in md if lo < k and (k <= d if inclusive else k < d)]
            return (max(vals), lo == last_end(d)) if vals else (None, False)
        in_event = lambda d: any(s_ <= d <= (e or 99999999) for s_, e in spans)
        firsts = [k * 100 + 1 for k in sorted({d // 100 for d in md}) if k >= BAYES_FROM]
        x0 = [x for x, _ in (xat(d) for d in firsts if not in_event(d)) if x is not None]
        x1 = [x for x, _ in (xat(s_) for s_, _ in spans if s_ >= BAYES_FROM * 100) if x is not None]
        pe = (sum(x >= MRI_LINE for x in x1) + 1) / (len(x1) + 2)
        pn = sum(x >= MRI_LINE for x in x0) / len(x0)
        hi, lo_ = pe / pn, (1 - pe) / (1 - pn)
        ongoing = bool(spans) and spans[-1][1] is None
        now, since_end = xat(md[-1], inclusive=True)
        lr = None
        if now is not None:
            w = 1 / (1 + math.exp(-(now - MRI_LINE) / MRI_WIDTH))
            lr = math.exp(math.log(lo_) + w * (math.log(hi) - math.log(lo_)))
        # the event needs x >= 75 when it starts, not now: over the next k months x may rise past the line or fall back.
        # q_j = the share of months since 2018 with x near today's (within 5, wider if too few) whose x j months later
        # was at or above 75; the factor for k months is the mean over j = 1..k of q_j * above + (1 - q_j) * below
        lr_k, q = {}, []
        if now is not None:
            mo = [k for k in sorted({d // 100 for d in md}) if k >= BAYES_FROM]
            X = {k: xat(k * 100 + 1)[0] for k in mo}
            for band in (5, 8, 12, 100):
                base = [k for k in mo if X[k] is not None and abs(X[k] - now) <= band and not in_event(k * 100 + 1)]
                if len(base) >= 20:
                    break
            for j in range(1, 13):
                fut = [X[add_months(k, j)] for k in base if X.get(add_months(k, j)) is not None]
                q.append(sum(f >= MRI_LINE for f in fut) / len(fut) if fut else pn)
            for k in (1, 3, 6, 12):
                lr_k[k] = round(st.mean(qq * hi + (1 - qq) * lo_ for qq in q[:k]), 4)
        bayes = {"mri6": None if now is None else round(now, 1), "lrK": lr_k, "q": [round(v, 2) for v in q], "sinceEnd": since_end, "lastEnd": last_end(md[-1] + 1),
                 "ongoing": ongoing, "line": MRI_LINE, "width": MRI_WIDTH, "lrHi": round(hi, 3), "lrLo": round(lo_, 3),
                 "lr": None if lr is None else round(lr, 4), "from": BAYES_FROM, "events": len(x1),
                 "eventsAbove": sum(x >= MRI_LINE for x in x1), "months": len(x0), "monthsAbove": round(pn, 3)}
    except (OSError, ValueError, KeyError, st.StatisticsError) as e:
        print(f"warning: bayes: {e}", file=sys.stderr)
    bt = None
    try:
        mri_d = {r[0]: r[7] * 100 for r in json.loads((DATA / "mri.json").read_text(encoding="utf-8"))["daily"]}
        bt = backtest(spans, mri_d, [r[0] for r in rows])
    except (OSError, ValueError, KeyError, st.StatisticsError, ZeroDivisionError) as e:
        print(f"warning: backtest: {e}", file=sys.stderr)
    lastday = max(days)
    data = {
        "source": "Cboe",
        "method": {"window": WINDOW, "fixedUntil": FIXED_UNTIL, "event": K_EVENT, "gap": GAP, "log10": True},
        "lastDay": lastday,
        "live": {"date": lv[0], "time": lv[2], "price": lv[1][3], "high": lv[1][1], "low": lv[1][2]} if lv else None,
        "quote": quote,
        "bayes": bayes,
        "backtest": bt,
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
