"""Build data/mri.json: the Market Risk Index (MRI) from VIX, SKEW and the Shiller PE (CAPE).

Method (『VIXの声を聴け』, 第一章):
  For each indicator, take month-end values (VIX and SKEW as log10). For every month, the
  deviation is (x - 10-year mean of x) / 10-year mean of x. Then take the 10-year mean and
  standard deviation of those deviations. Risk = NORMDIST(deviation, mean, sd); for VIX it is
  1 - NORMDIST, because a calm market is the risky one. MRI is the average of the three.

Rolling across months: the statistics are recomputed from the last 120 completed months each
time a month ends, and every day of the next month is scored against them. CAPE is monthly, so
a daily CAPE is the S&P 500 close divided by the 10-year earnings (E10 = monthly price / CAPE),
with E10 interpolated day by day between months.

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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "mri.json"
CACHE = DATA / "sources.json"  # monthly and long histories, refreshed hourly
STATUS = DATA / "status.json"
NY = ZoneInfo("America/New_York")
WINDOW = 120  # months
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})


def get(url, **kw):
    last = None
    for attempt in range(3):
        if attempt:
            time.sleep(4 * attempt)
        try:
            r = session.get(url, timeout=30, **kw)
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


def fred_spx_daily():
    """S&P 500 daily closes from FRED (about the last ten years)."""
    text = get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500").text
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


def cboe_live(symbol):
    """(yyyymmdd, value, time) from Cboe's delayed quote, or None."""
    j = get(f"https://cdn.cboe.com/api/global/delayed_quotes/quotes/_{symbol}.json").json()
    q = j.get("data") or {}
    price = q.get("current_price") or q.get("close")
    stamp = q.get("last_trade_time") or j.get("timestamp")
    if not price or not stamp:
        return None
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo:
        dt = dt.astimezone(NY)
    return ymd(dt), float(price), dt.strftime("%Y-%m-%d %H:%M")


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
    spx.update(fred_spx_daily())  # keeps everything collected so far, adds the latest ten years
    out["spx"] = spx
    return out, True


# ---------- method ----------

def month_ends(daily):
    """{yyyymm: last value of the month} from {yyyymmdd: value}."""
    out = {}
    for d in sorted(daily):
        out[d // 100] = daily[d]
    return out


def months_back(ym, n):
    y, m = divmod(ym, 100)
    t = y * 12 + (m - 1) - n
    return (t // 12) * 100 + t % 12 + 1


def stats_by_month(monthly, log):
    """For each month M with enough history: (mean, devMean, devSD) from the 120 months ending at M."""
    x = {k: (math.log10(v) if log else v) for k, v in monthly.items() if v > 0}
    keys = sorted(x)
    dev = {}
    for k in keys:
        win = [x[j] for j in keys if months_back(k, WINDOW - 1) <= j <= k]
        if len(win) >= WINDOW:
            mu = sum(win) / len(win)
            dev[k] = (x[k] - mu) / mu
    out = {}
    for k in keys:
        win_x = [x[j] for j in keys if months_back(k, WINDOW - 1) <= j <= k]
        win_d = [dev[j] for j in dev if months_back(k, WINDOW - 1) <= j <= k]
        if len(win_x) >= WINDOW and len(win_d) >= WINDOW:
            out[k] = (sum(win_x) / len(win_x), sum(win_d) / len(win_d), statistics.stdev(win_d))
    return out


def norm_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def risk(v, st, log, invert):
    mu, dmu, dsd = st
    x = math.log10(v) if log else v
    p = norm_cdf(((x - mu) / mu - dmu) / dsd)
    return 1 - p if invert else p


def daily_e10(spx_m, cape_m):
    """E10 placed on the 15th of each month, interpolated day by day."""
    pts = sorted((date(k // 100, k % 100, 15), spx_m[k] / cape_m[k]) for k in cape_m if k in spx_m and cape_m[k] > 0)

    def at(d):
        if d <= pts[0][0]:
            return pts[0][1]
        if d >= pts[-1][0]:
            return pts[-1][1]
        lo, hi = 0, len(pts) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if pts[mid][0] <= d:
                lo = mid
            else:
                hi = mid
        (d0, e0), (d1, e1) = pts[lo], pts[hi]
        return e0 + (e1 - e0) * (d - d0).days / (d1 - d0).days
    return at


def sig(x, n=6):
    return float(f"{x:.{n}g}")


def build():
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    for k in ("vix", "skew", "spx"):
        if k in cache:
            cache[k] = {int(d): v for d, v in cache[k].items()}
    for k in ("cape_m", "spx_m"):
        if k in cache:
            cache[k] = {int(d): v for d, v in cache[k].items()}
    src, refreshed = load_sources(cache)
    vix, skew, spx = dict(src["vix"]), dict(src["skew"]), dict(src["spx"])

    # latest values (delayed quotes) for today
    live = {}
    for name, fn in (("vix", lambda: cboe_live("VIX")), ("skew", lambda: cboe_live("SKEW")), ("spx", lambda: cboe_live("SPX"))):
        try:
            q = fn()
        except (RuntimeError, ValueError, KeyError) as e:
            print(f"warning: live {name}: {e}", file=sys.stderr)
            q = None
        if q:
            live[name] = {"date": q[0], "value": q[1], "time": q[2]}
            {"vix": vix, "skew": skew, "spx": spx}[name][q[0]] = q[1]

    # statistics per completed month, and the CAPE month series including multpl's live month
    cape_m, spx_m = src["cape_m"], src["spx_m"]
    today_m = ymd(datetime.now(NY).date()) // 100
    st = {"vix": stats_by_month({k: v for k, v in month_ends(vix).items() if k < today_m}, True),
          "skew": stats_by_month({k: v for k, v in month_ends(skew).items() if k < today_m}, True),
          "cape": stats_by_month({k: v for k, v in cape_m.items() if k < today_m}, False)}
    e10 = daily_e10(spx_m, cape_m)

    def stats_for(day, which):
        m = day // 100
        prev = months_back(m, 1)
        return st[which].get(prev)

    rows = []
    for d in sorted(set(vix) & set(skew) & set(spx)):
        sv, ss, sc = stats_for(d, "vix"), stats_for(d, "skew"), stats_for(d, "cape")
        if not (sv and ss and sc):
            continue
        cape = spx[d] / e10(date(d // 10000, d // 100 % 100, d % 100))
        vr, sr, cr = risk(vix[d], sv, True, True), risk(skew[d], ss, True, False), risk(cape, sc, False, False)
        rows.append([d, sig(vix[d], 5), sig(skew[d], 5), sig(cape, 5), round(vr, 5), round(sr, 5), round(cr, 5),
                     round((vr + sr + cr) / 3, 5)])
    if not rows:
        raise RuntimeError("no days with all three indicators")

    last_m = max(st["vix"])
    data = {
        "source": "Cboe, multpl.com, FRED",
        "stats": {k: {"month": max(v), "mean": sig(v[max(v)][0], 7), "devMean": sig(v[max(v)][1], 6),
                      "devSD": sig(v[max(v)][2], 6)} for k, v in st.items()},
        "live": live,
        # the statistics the March 2026 version of the app had fixed, for comparison
        "check": {k: v.get(202602) for k, v in st.items()},
        "daily": rows,
    }
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
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
    print(f"updated: {len(rows)} days {rows[0][0]}..{r[0]}, MRI {r[7]:.4f} (VIX {r[1]} SKEW {r[2]} CAPE {r[3]}); "
          f"stats month {last_m}")


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
