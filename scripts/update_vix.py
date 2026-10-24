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
BAYES_FROM, MRI_LINE, MRI_WIDTH, QUIET = 201801, 75, 3, 6


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


def model(spans, mri, months, today):
    """The event probability, now and at the start of each past month (the backtest).

    Random: events come with the same chance every month outside events, lam_r = events / months outside events.
    Interval: no event has come within 6 months of the previous one ending (0 in 60 such months, against about 1 in
    30 otherwise), so the hazard is 0 during an event and for 6 months after it ends, and constant after that:
    lam_q = events / months outside events and those quiet periods. Over k months, P = 1 - exp(-lam_q * months of
    the k that are past the quiet period).
    MRI (from 2018, when it works): x = the highest daily MRI over the last 6 months, or since the last event ended if
    that is more recent. Every event so far came with x at or above 75, but so did many quiet months: the line works
    as a step. The likelihood ratio is P(x >= 75 | before an event) / P(x >= 75 | other months) above the line and
    the same for below, the event share smoothed by Laplace's rule (+1 / +2). What counts is x when an event starts,
    not now: q_j = the share of months with x near today's (within 5, wider if too few) whose x j months later was
    at or above 75, and the factor for k months is the mean over j = 1..k of q_j * above + (1 - q_j) * below.
    Bayes: posterior odds = interval odds x MRI factor.
    Backtest rows: [month, during an event (1/0), then for "in" (parameters from all the data) and "out" (only what
    was known then) the Bayes, interval and random probabilities for 1, 3, 6 and 12 months, in %]."""
    import bisect
    md = sorted(mri)
    idx = lambda m: m // 100 * 12 + m % 100
    smon = [s_ // 100 for s_, _ in spans]
    odds = lambda p: p / (1 - p)
    def last_end(d):
        ends = [e for s_, e in spans if e and e < d]
        return max(ends) if ends else 0
    def xat(d, inclusive=False):
        lo = max(last_end(d), add_months(d // 100, -6) * 100 + d % 100)
        hi_ = bisect.bisect_right(md, d) if inclusive else bisect.bisect_left(md, d)
        vals = [mri[k] for k in md[bisect.bisect_right(md, lo):hi_]]
        return (max(vals), lo == last_end(d)) if vals else (None, False)
    in_event = lambda d: any(s_ <= d <= (e or 99999999) for s_, e in spans)
    ongoing_at = lambda d: any(s_ < d and (e is None or e >= d) for s_, e in spans)
    def quiet_until(d):  # the month index from which events can come again
        e = last_end(d)
        return idx(e // 100) + QUIET if e else -1
    ONG = {m: ongoing_at(m * 100 + 1) for m in months}
    QM = {m: idx(m) < quiet_until(m * 100 + 1) for m in months}
    def rates(upto):
        ms = [m for m in months if upto is None or m < upto]
        n = sum(1 for s_ in smon if upto is None or s_ < upto)
        free = [m for m in ms if not ONG[m]]
        act = [m for m in free if not QM[m]]
        return n / len(free), n / len(act)
    mm = [m for m in months if m >= BAYES_FROM]
    X = {m: xat(m * 100 + 1)[0] for m in mm}
    XE = {s_: xat(s_)[0] for s_, _ in spans if s_ >= BAYES_FROM * 100}
    def mri_params(upto):
        xe = [x for s_, x in XE.items() if x is not None and (upto is None or s_ < upto * 100 + 1)]
        xn = [X[k] for k in mm if X[k] is not None and not in_event(k * 100 + 1) and (upto is None or k < upto)]
        if not xe or len(xn) < 6:
            return None
        pe = (sum(x >= MRI_LINE for x in xe) + 1) / (len(xe) + 2)
        pn = sum(x >= MRI_LINE for x in xn) / len(xn)
        if pn in (0, 1):
            return None
        return {"hi": pe / pn, "lo": (1 - pe) / (1 - pn), "pn": pn, "events": len(xe),
                "eventsAbove": sum(x >= MRI_LINE for x in xe), "months": len(xn)}
    def factors(x, par, upto):
        known = lambda k: upto is None or k < upto
        for band in (5, 8, 12, 100):
            base = [k for k in mm if X[k] is not None and abs(X[k] - x) <= band and not in_event(k * 100 + 1) and known(k)]
            if len(base) >= 20:
                break
        q = []
        for j in range(1, 13):
            fut = [X[add_months(k, j)] for k in base if X.get(add_months(k, j)) is not None and known(add_months(k, j))]
            q.append(sum(f >= MRI_LINE for f in fut) / len(fut) if len(fut) >= 3 else par["pn"])
        return q, {k: st.mean(qq * par["hi"] + (1 - qq) * par["lo"] for qq in q[:k]) for k in (1, 3, 6, 12)}
    def probs(m, ongoing, qu, lam, fk):
        lam_r, lam_q = lam
        out = []
        for k in (1, 3, 6, 12):
            act = sum(1 for j in range(k) if idx(m) + j >= qu)
            b = 1 - math.exp(-lam_r * k)
            pi = 0 if ongoing else 1 - math.exp(-lam_q * act)
            o = odds(pi) * fk.get(k, 1) if 0 < pi < 1 else 0
            out.append((k, o / (1 + o), pi, b))
        return out
    # now
    par_in = mri_params(None)
    lam_in = rates(None)
    ongoing = bool(spans) and spans[-1][1] is None
    now, since_end = xat(md[-1], inclusive=True)
    q, fk = factors(now, par_in, None) if now is not None and par_in else ([], {})
    cur = months[-1]
    qu = quiet_until(today + 1)
    lr = None
    if now is not None and par_in:
        w = 1 / (1 + math.exp(-(now - MRI_LINE) / MRI_WIDTH))
        lr = math.exp(math.log(par_in["lo"]) + w * (math.log(par_in["hi"]) - math.log(par_in["lo"])))
    bayes = {"mri6": None if now is None else round(now, 1), "sinceEnd": since_end, "lastEnd": last_end(today + 1),
             "ongoing": ongoing, "quiet": QUIET, "quietLeft": max(0, qu - idx(cur)), "lamR": round(lam_in[0], 5),
             "lamQ": round(lam_in[1], 5), "line": MRI_LINE, "width": MRI_WIDTH, "from": BAYES_FROM,
             "lr": None if lr is None else round(lr, 4), "lrK": {k: round(v, 4) for k, v in fk.items()},
             "q": [round(v, 2) for v in q],
             "prob": [{"k": k, "post": round(p, 5), "int": round(pi, 5), "base": round(b, 5)}
                      for k, p, pi, b in probs(cur, ongoing, qu, lam_in, fk)]}
    if par_in:
        bayes.update({"lrHi": round(par_in["hi"], 3), "lrLo": round(par_in["lo"], 3), "events": par_in["events"],
                      "eventsAbove": par_in["eventsAbove"], "months": par_in["months"], "monthsAbove": round(par_in["pn"], 3)})
    # backtest
    rows = []
    for m in months:
        if m <= smon[0]:
            continue
        d = m * 100 + 1
        row = [m, int(ONG[m])]
        for mode in ("in", "out"):
            upto = None if mode == "in" else m
            par = par_in if mode == "in" else mri_params(m)
            x = X.get(m)
            fkm = factors(x, par, upto)[1] if x is not None and par else {}
            pr = probs(m, ONG[m], quiet_until(d), lam_in if mode == "in" else rates(m), fkm)
            row += [round(v[c] * 100, 2) for c in (1, 2, 3) for v in pr]
        rows.append(row)
    return bayes, rows


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
    # the event probability (Bayes: interval x MRI) and its backtest; see model()
    bayes = bt = None
    try:
        mri_d = {r[0]: r[7] * 100 for r in json.loads((DATA / "mri.json").read_text(encoding="utf-8"))["daily"]}
        bayes, bt = model(spans, mri_d, [r[0] for r in rows], dl[-1])
    except (OSError, ValueError, KeyError, st.StatisticsError, ZeroDivisionError) as e:
        print(f"warning: bayes: {e}", file=sys.stderr)
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
