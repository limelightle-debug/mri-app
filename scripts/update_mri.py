"""Build data/mri.json: the Market Risk Index (MRI) from VIX, SKEW and the Shiller PE (CAPE).

Method (『VIXの声を聴け』, 第一章):
  For each indicator, take month-end values (VIX and SKEW as log10). For every month, the
  deviation is (x - 10-year mean of x) / 10-year mean of x. Then take the 10-year mean and
  standard deviation of those deviations. Risk = NORMDIST(deviation, mean, sd); for VIX it is
  1 - NORMDIST, because a calm market is the risky one. MRI is the average of the three.

As in the MRI workbook, today's value is the current month's row, so the 120 months include it;
history is scored the same way, each day as its month's row. VIX and SKEW are Cboe's month-end
closes; CAPE is multpl.com's monthly table (revised values) for completed months. A day's CAPE is
that day's S&P 500 close divided by that month's E10; the current month uses the
last completed month's E10, so multpl.com's current-month figures are not used.

Sources: Cboe (VIX and SKEW history, delayed quotes for VIX, SKEW and the S&P 500), multpl.com
(monthly CAPE and S&P 500 price), FRED (S&P 500 daily closes). Runs in GitHub Actions.
"""
import csv
import io
import json
import math
import re
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from mkt_calendar import gth_morning_holiday, is_trading_day
from skew_calc import SANE_SKEW, SANE_VIX

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "mri.json"
CACHE = DATA / "sources.json"  # long histories, refreshed hourly; kept only for the run (not committed)
STATUS = DATA / "status.json"
NY = ZoneInfo("America/New_York")
WINDOW = 120  # months
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})


def get(url, timeout=30, tries=3, **kw):
    last = None
    for attempt in range(tries):
        if attempt:
            time.sleep(4 * attempt)
        try:
            r = session.get(url, timeout=timeout, **kw)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
    raise RuntimeError(f"{url.split('?')[0]}: {last}")


def num(s):
    return float(str(s).replace("$", "").replace(",", "").strip())


def ymd(d):
    return d.year * 10000 + d.month * 100 + d.day


# ---------- sources ----------

def cboe_history(name):
    """Daily closes {yyyymmdd: value} from Cboe's history file."""
    text = get(f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{name}_History.csv").text
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        row = {k.strip().upper(): v for k, v in row.items() if k}
        try:
            m, d, y = row["DATE"].split("/")
            v = num(row.get("CLOSE") or row.get(name))
        except (KeyError, ValueError):
            continue
        if v > 0:
            out[int(y) * 10000 + int(m) * 100 + int(d)] = v
    if len(out) < 1000:
        raise RuntimeError(f"Cboe {name}: only {len(out)} days")
    return out


def multpl_monthly(path):
    """{yyyymm: value} from a multpl.com 'table/by-month' page. The newest row is the live estimate."""
    html = get(f"https://www.multpl.com/{path}/table/by-month").text
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>|&[#\w]+;", " ", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 2:
            continue
        m = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", cells[0])
        v = re.search(r"\d[\d,]*\.?\d*", cells[1])
        if not m or not v:
            continue
        dt = datetime.strptime(m.group(0), "%b %d, %Y")
        out.setdefault(dt.year * 100 + dt.month, num(v.group(0)))  # first (newest) row of each month
    if len(out) < 240:
        raise RuntimeError(f"multpl {path}: only {len(out)} months")
    return out


def stooq_spx_daily():
    text = get("https://stooq.com/q/d/l/?s=%5Espx&i=d", timeout=60, tries=2).text
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            y, m, d = map(int, row["Date"].split("-"))
            out[y * 10000 + m * 100 + d] = float(row["Close"])
        except (KeyError, ValueError):
            continue
    if len(out) < 500:
        raise RuntimeError(f"stooq ^SPX: only {len(out)} days")
    return out


def spx_daily():
    """S&P 500 daily closes from the first source that answers; also says which one it was."""
    errors = []
    for name, fn in (("Cboe", lambda: cboe_history("SPX")), ("FRED", fred_spx_daily), ("stooq", stooq_spx_daily)):
        try:
            return fn(), name
        except (RuntimeError, ValueError) as e:
            errors.append(f"{name}: {e}"[:160])
    raise RuntimeError("S&P 500 daily: " + " | ".join(errors))


def fred_spx_daily():
    """S&P 500 daily closes from FRED (about the last ten years)."""
    text = get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500", timeout=90, tries=2).text
    out = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or not re.match(r"\d{4}-\d{2}-\d{2}$", row[0]):
            continue
        try:
            v = float(row[1])
        except ValueError:
            continue  # holidays are "."
        y, m, d = map(int, row[0].split("-"))
        out[y * 10000 + m * 100 + d] = v
    if len(out) < 500:
        raise RuntimeError(f"FRED SP500: only {len(out)} days")
    return out


def session_day(t):
    """The trading day a moment belongs to: the overnight session from 20:15 ET counts toward the
    next trading day (weekends and market holidays skipped)."""
    d = t.date()
    if t.hour * 60 + t.minute >= 20 * 60 + 15:
        d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return ymd(d)


def cboe_live(symbol):
    """(yyyymmdd, value, time) from Cboe's delayed quote, or None.

    Overnight (VIX trades from 20:15 ET), Cboe's quote keeps the regular close's time but its
    current price moves: that price is returned under the coming session's day, so it never
    overwrites the close."""
    j = get(f"https://cdn.cboe.com/api/global/delayed_quotes/quotes/_{symbol}.json").json()
    q = j.get("data") or {}
    price = q.get("current_price") or q.get("close")
    stamp = q.get("last_trade_time")
    if not price or not stamp:
        return None
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        fetched = datetime.strptime(str(j.get("timestamp"))[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(NY)
    except ValueError:
        return None
    dt = dt.astimezone(NY) if dt.tzinfo else dt.replace(tzinfo=NY)
    day = ymd(dt)
    regular_close = dt.hour * 60 + dt.minute >= 16 * 60
    if regular_close and session_day(fetched) > day:
        # after the close: a moving price belongs to the next session, and so does any price during
        # VIX's overnight session (20:15 ET Sun-Thu to 9:30 ET), even before it first moves
        close = q.get("close")
        fm, fwd = fetched.hour * 60 + fetched.minute, fetched.weekday()
        night = ((fwd in (6, 0, 1, 2, 3) and fm >= 20 * 60 + 15) or (fwd < 5 and fm < 9 * 60 + 30)
                 or (gth_morning_holiday(fetched.date()) and fm < 11 * 60 + 30))  # GTH runs on a holiday's morning
        if symbol == "VIX" and close and (abs(float(price) - float(close)) > 1e-9 or night):
            return session_day(fetched), float(price), fetched.strftime("%Y-%m-%d %H:%M"), day, float(close)
        return day, float(close or price), dt.strftime("%Y-%m-%d %H:%M"), day, float(close or price)
    return day, float(price), dt.strftime("%Y-%m-%d %H:%M"), day, float(price)


SKEW_CALC = DATA / "skew_calc.json"


def calc_time():
    """When the option quotes behind the estimates were published ("YYYY-MM-DD HH:MM", New York)."""
    try:
        return datetime.fromisoformat(json.loads(SKEW_CALC.read_text(encoding="utf-8"))["quoteTime"]).astimezone(NY).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError, KeyError):
        return datetime.now(NY).strftime("%Y-%m-%d %H:%M")


def calc_usable(j):
    """The option quotes reach far enough out of the money for VIX and SKEW to mean something. Before a session
    opens (Sunday evening, say) only quotes near the money carry bids, and both come out far too low."""
    terms = j.get("terms") or []
    return bool(terms) and all(t.get("lowK") and t.get("F") and t["lowK"] <= 0.8 * t["F"] for t in terms)


def skew_change(prev):
    """How much the SKEW recomputed from the option quotes has moved since the close of `prev`."""
    try:
        j = json.loads(SKEW_CALC.read_text(encoding="utf-8"))
        at = datetime.fromisoformat(j["quoteTime"]).astimezone(NY)
        anchor = j.get("anchors", {}).get(str(prev))
    except (OSError, ValueError, KeyError):
        return None
    # the estimate must be fresh and from a later session (overnight counts), with a close-time
    # estimate for `prev`
    if anchor is None or (datetime.now(NY) - at).total_seconds() > 4 * 3600 or session_day(at) <= prev or not calc_usable(j):
        return None
    if j.get("skew") is None:
        return None
    # against the close-time value, not just the last result (which a weekend makes stale, so broken snapshots that
    # agree with each other got through); the bounds are skew_calc's (SANE_SKEW)
    return None if abs(j["skew"] - anchor) > SANE_SKEW else j["skew"] - anchor


def vix_estimate(prev, close):
    """VIX recomputed from the option quotes: the close of `prev` moved by its ratio to the value at
    that close; without that value, the recomputed VIX itself (it tracks Cboe's closely)."""
    try:
        j = json.loads(SKEW_CALC.read_text(encoding="utf-8"))
        at = datetime.fromisoformat(j["quoteTime"]).astimezone(NY)
        base, cur = j.get("anchorsV", {}).get(str(prev)), j.get("vix")
    except (OSError, ValueError, KeyError):
        return None
    if not cur or (datetime.now(NY) - at).total_seconds() > 4 * 3600 or session_day(at) <= prev or not calc_usable(j):
        return None
    # VIX can jump overnight but does not lose half of itself (its lowest low against the previous close is 0.59,
    # 2020-03-24): a recomputed value that far below its close-time value comes from broken quotes
    if base and cur / base < SANE_VIX:
        return None
    return close * cur / base if base else cur


def spx_ratio(prev):
    """How much the S&P 500 forward implied by the options has moved since the close of `prev`
    (same expiry), for the hours the index itself does not trade."""
    try:
        j = json.loads(SKEW_CALC.read_text(encoding="utf-8"))
        at = datetime.fromisoformat(j["quoteTime"]).astimezone(NY)
        base, now_f = j.get("anchorsF", {}).get(str(prev), {}), j.get("forwards", {})
    except (OSError, ValueError, KeyError):
        return None
    if (datetime.now(NY) - at).total_seconds() > 4 * 3600 or session_day(at) <= prev:
        return None
    common = [e for e in now_f if e in base and base[e]]
    if common:
        return now_f[common[0]] / base[common[0]]
    # the chain moved on to later expiries (after a weekend, say): the close-time forward at the new expiry from the
    # two close-time expiries, in a straight line (the carry between expiries a few days apart is tiny)
    try:
        bk = sorted((datetime.fromisoformat(e), v) for e, v in base.items() if v)
        e0, f0 = min(((datetime.fromisoformat(e), v) for e, v in now_f.items() if v), key=lambda x: x[0])
    except (ValueError, TypeError):
        return None
    if not bk:
        return None
    if len(bk) >= 2 and (bk[-1][0] - bk[0][0]).total_seconds() > 0:
        slope = (bk[-1][1] - bk[0][1]) / (bk[-1][0] - bk[0][0]).total_seconds()
        fb = bk[-1][1] + slope * (e0 - bk[-1][0]).total_seconds()
    else:
        fb = bk[-1][1]
    return f0 / fb if fb else None


def load_sources(cache):
    fresh = cache.get("fetchedAt")
    if fresh and (datetime.now(timezone.utc) - datetime.fromisoformat(fresh)).total_seconds() < 3600:
        return cache, False
    out = {"fetchedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")}
    out["vix"] = cboe_history("VIX")
    out["skew"] = cboe_history("SKEW")
    out["cape_m"] = multpl_monthly("shiller-pe")
    out["spx_m"] = multpl_monthly("s-p-500-historical-prices")
    spx = {int(k): v for k, v in (cache.get("spx") or {}).items()}
    got, out["spxSource"] = spx_daily()
    spx.update(got)  # keeps everything collected so far, adds what the source has
    out["spx"] = spx
    return out, True


# ---------- method ----------

def month_ends(daily):
    """{yyyymm: last value of the month} from {yyyymmdd: value}."""
    out = {}
    for d in sorted(daily):
        out[d // 100] = daily[d]
    return out


def month_means(daily):
    """{yyyymm: average of the month's closes}."""
    acc = {}
    for d, v in daily.items():
        a = acc.setdefault(d // 100, [0.0, 0])
        a[0] += v
        a[1] += 1
    return {k: s / n for k, (s, n) in acc.items()}


def norm_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


class Indicator:
    """One indicator as the MRI workbook computes it.

    Month rows hold month-end values. For a row, the 10-year mean covers that row and the 119
    rows before it; deviation = (x - mean) / mean; the deviation's mean and STDEV cover the same
    120 rows. The current month is a row whose value is today's value, so its statistics include
    today (that is how the workbook's latest row works)."""

    def __init__(self, monthly, log, invert):
        self.log, self.invert = log, invert
        self.keys = sorted(monthly)
        self.x = [self.tr(monthly[k]) for k in self.keys]
        self.idx = {k: i for i, k in enumerate(self.keys)}
        self.dev = [None] * len(self.x)
        for i in range(WINDOW - 1, len(self.x)):
            mu = sum(self.x[i - WINDOW + 1:i + 1]) / WINDOW
            self.dev[i] = (self.x[i] - mu) / mu

    def tr(self, v):
        return math.log10(v) if self.log else v

    def score(self, month, value):
        """Risk of `value` taken as the row for `month` (rows before it are the month-end values)."""
        n = sum(1 for k in self.keys if k < month)  # rows before this month
        if n < 2 * WINDOW - 2:
            return None
        xs = self.x[n - WINDOW + 1:n] + [self.tr(value)]
        mu = sum(xs) / WINDOW
        d = (xs[-1] - mu) / mu
        devs = self.dev[n - WINDOW + 1:n] + [d]
        if any(v is None for v in devs):
            return None
        p = norm_cdf((d - sum(devs) / WINDOW) / statistics.stdev(devs))
        return 1 - p if self.invert else p


def sig(x, n=6):
    return float(f"{x:.{n}g}")


MONTHLY_CSV = DATA / "monthly.csv"  # month-end VIX, SKEW and CAPE used for the statistics


def build():
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    for k in ("vix", "skew", "spx", "cape_m", "spx_m"):
        if k in cache:
            cache[k] = {int(d): v for d, v in cache[k].items()}
    src, refreshed = load_sources(cache)
    vix, skew, spx = dict(src["vix"]), dict(src["skew"]), dict(src["spx"])
    cape_m, spx_m = src["cape_m"], src["spx_m"]

    # latest values (Cboe delayed quotes) for today
    live = {}
    for name, sym in (("vix", "VIX"), ("skew", "SKEW"), ("spx", "SPX")):
        try:
            q = cboe_live(sym)
        except (RuntimeError, ValueError, KeyError) as e:
            print(f"warning: live {name}: {e}", file=sys.stderr)
            q = None
        if q:
            live[name] = {"date": q[0], "value": q[1], "time": q[2]}
            series = {"vix": vix, "skew": skew, "spx": spx}[name]
            series[q[3]] = q[4]  # the close keeps its own day
            series[q[0]] = q[1]

    now = datetime.now(NY)
    today = session_day(now)
    cur_m = today // 100
    # SKEW is published once a day, after the close. During the session (once VIX has a value for
    # the day), today's SKEW is the last official close moved by how much the SKEW recomputed from
    # the option quotes has changed since that close; without that estimate, the close is carried.
    # overnight, Cboe's VIX quote may still show the close: then VIX is the close moved by the change in
    # the VIX recomputed from the option quotes (the same options Cboe uses overnight)
    lv = live.get("vix", {})
    if today in vix and lv.get("date") == today:
        prevv = max(d for d in vix if d < today)
        if abs(vix[today] - vix[prevv]) < 1e-9:
            est = vix_estimate(prevv, vix[prevv])
            if est:
                vix[today] = est
                live["vix"] = {**lv, "value": round(vix[today], 2), "estimate": True, "close": vix[prevv],
                               "time": calc_time()}
    if today in vix and today not in skew and skew:
        prev = max(d for d in skew if d < today)
        chg = skew_change(prev)
        if chg is not None:
            est = skew[prev] + chg
            skew[today] = est
            live["skew"] = {"date": today, "value": round(est, 2), "time": calc_time(),
                            "estimate": True, "close": skew[prev]}
        else:
            skew[today] = skew[prev]
            live["skew"] = {"date": today, "value": skew[prev], "time": live.get("skew", {}).get("time", ""),
                            "carried": True}
    # the S&P 500 does not trade overnight: its last close stands for the session until it opens
    if today in vix and today not in spx and spx:
        prev = max(spx)
        r = spx_ratio(prev)
        spx[today] = spx[prev] * (r or 1)
        live["spx"] = {**live.get("spx", {}), "date": today, "value": round(spx[today], 2),
                       **({"estimate": True, "close": spx[prev], "time": calc_time()} if r else {"carried": True})}
    last_day = max(set(vix) & set(skew))
    cur_m = max(cur_m, last_day // 100)

    # month rows: VIX and SKEW at Cboe's month-end closes, CAPE from multpl.com's monthly table
    # (with its revisions); the current month holds today's values
    vme, kme = month_ends(vix), month_ends(skew)
    months = {m: {"vix": vme[m], "skew": kme[m], "cape": cape_m[m]}
              for m in sorted(set(vme) & set(kme) & set(cape_m)) if m < cur_m}
    # the current month does not use multpl.com's current-month figures (they update at random times,
    # hours after the close, and its price and CAPE rows do not always update together): its E10 is the
    # last completed month's (Cboe's average close for that month / multpl.com's CAPE for it), and its
    # CAPE is this month's average close so far over that E10
    avg = month_means(spx)
    e10_m = {m: avg[m] / r["cape"] for m, r in months.items()}
    # multpl.com finalises a month hours after its last close (later still when the month ends on a
    # Friday: Saturday morning in Japan). Its price for a finished month is exactly Cboe's average close
    # for that month, so until the two agree, the last month is not final yet: it keeps the E10 of the
    # month before, like the current month
    prev_m = max(months)
    if abs(spx_m.get(prev_m, 0) - avg[prev_m]) > .006 and len(months) > 1:
        e10_m[prev_m] = e10_m[max(m for m in months if m < prev_m)]
        months[prev_m]["cape"] = avg[prev_m] / e10_m[prev_m]
        print(f"note: multpl.com has not finalised {prev_m} yet", file=sys.stderr)
    e10_cur = e10_m[prev_m]
    if cur_m in vme and cur_m in kme and cur_m in avg:
        months[cur_m] = {"vix": vme[cur_m], "skew": kme[cur_m], "cape": avg[cur_m] / e10_cur}
        e10_m[cur_m] = e10_cur
    # the same month-end values as a table, to check or correct a spreadsheet against
    lines = ["month,VIX,SKEW,CAPE"] + [f"{m // 100}-{m % 100:02d},{r['vix']},{r['skew']},{r['cape']}"
                                      for m, r in months.items() if m < cur_m]
    csv_text = "\n".join(lines) + "\n"
    if not MONTHLY_CSV.exists() or MONTHLY_CSV.read_text(encoding="utf-8") != csv_text:
        MONTHLY_CSV.write_text(csv_text, encoding="utf-8")

    # one indicator over all month rows; `score` only uses the rows before the month it is asked about
    ind = {"vix": Indicator({m: r["vix"] for m, r in months.items()}, True, True),
           "skew": Indicator({m: r["skew"] for m, r in months.items()}, True, False),
           "cape": Indicator({m: r["cape"] for m, r in months.items()}, False, False)}
    # the S&P 500 itself, scored the same way (month-end closes, no log), for comparison on the chart
    spx_me = {m: v for m, v in month_ends(spx).items() if m <= cur_m}
    ind_spx = Indicator(spx_me, False, False)

    # daily CAPE: the day's S&P 500 close divided by the month's E10
    # (E10 = month average / month CAPE; for the current month, the last completed month's)
    rows = []
    for d in sorted(set(vix) & set(skew) & set(spx)):
        m = d // 100
        if m not in months:
            continue
        # the day's CAPE: that day's close over the month's E10 (like multpl.com's current value), so it
        # moves with the index; every day the same way, today included
        cape = spx[d] / e10_m.get(m, e10_cur)
        vr, sr, cr = ind["vix"].score(m, vix[d]), ind["skew"].score(m, skew[d]), ind["cape"].score(m, cape)
        pr = ind_spx.score(m, spx[d])
        if None in (vr, sr, cr):
            continue
        rows.append([d, sig(vix[d], 5), sig(skew[d], 5), sig(cape, 5), round(vr, 5), round(sr, 5), round(cr, 5),
                     round((vr + sr + cr) / 3, 5), sig(spx[d], 6),
                     None if pr is None else round(pr, 5)])
    if not rows:
        raise RuntimeError("no days with all three indicators")

    # the last row is provisional while the day's SKEW is not official yet (estimated or carried)
    sk = live.get("skew", {})
    live_day = today if rows[-1][0] == today and sk.get("date") == today and (sk.get("estimate") or sk.get("carried")) else None
    # each live value's time as an ISO timestamp (the quote times are New York time)
    for v in live.values():
        try:
            v["at"] = datetime.strptime(v.get("time", ""), "%Y-%m-%d %H:%M").replace(tzinfo=NY).isoformat()
        except ValueError:
            pass
    data = {"source": f"Cboe, multpl.com, {src.get('spxSource', '')}", "live": live, "liveDay": live_day, "daily": rows}
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    # the realtime MRI through the session, one point per update: [time, MRI, VIX, SKEW, CAPE risk]
    intra = old.get("intraday") or {}
    if live_day:
        if intra.get("day") != live_day:
            intra = {"day": live_day, "points": []}
        # the previous day's confirmed MRI, from this build (it changes when that day's values or the method do)
        before = [r for r in rows if r[0] < live_day]
        intra["prevClose"] = before[-1][7] if before else None
        r = rows[-1]
        pt = [now.isoformat(timespec="minutes"), r[7], r[4], r[5], r[6]]
        pts = intra["points"]
        if pts and pts[-1][0] == pt[0]:
            pts[-1] = pt
        else:
            pts.append(pt)
        # drop a lone spike (a point 8+ MRI points away from both neighbours, which agree with each other)
        intra["points"] = [q for i, q in enumerate(pts) if not (0 < i < len(pts) - 1
                           and abs(pts[i - 1][1] - pts[i + 1][1]) < .03
                           and min(abs(q[1] - pts[i - 1][1]), abs(q[1] - pts[i + 1][1])) > .08)]
    if intra:
        data["intraday"] = intra
    if refreshed:
        cache_out = {k: ({str(d): v for d, v in src[k].items()} if isinstance(src[k], dict) else src[k]) for k in src}
        CACHE.write_text(json.dumps(cache_out, separators=(",", ":")), encoding="utf-8")
    prev = dict(old)
    prev.pop("updatedAt", None)
    if prev == data:
        print("no change")
        return
    data = {"updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **data}
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    r = rows[-1]
    print(f"updated: {len(rows)} days {rows[0][0]}..{r[0]}, MRI {r[7]:.4f} (VIX {r[1]} SKEW {r[2]} CAPE {r[3]})")


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    try:
        build()
        result = {"ok": True}
    except Exception as e:  # leave the reason in the repo so it can be read without signing in
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"[:500],
                  "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    old = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else None
    if old != result:
        STATUS.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
