"""Data for the institute's "Money" app (rates, quantity, yardsticks): data/money.json.

Built on the framework of 『金利の重力』 (Gold Locks) and 『帳簿と物差し』:
- real: the Treasury's daily par yield curves, nominal (2Y, 10Y, 30Y) and real (5Y, 10Y, 30Y), from 2003 (the
  first year of the real curve, as FRED's DFII10). Daily rows for the last 6 years, monthly averages for all.
  Past years are kept from the last run; only the current year (and the last one in January) is downloaded.
- gravity: 第十二章's indicator. The monthly 10-year real yield minus its 10-year moving average, divided by the
  standard deviation of that difference (window: 10 years at most, 24 months at least), with the S&P 500 at the
  month's end and 12 months later.
- cape: 第十章's adjusted CAPE gap. CAPE over its 10-year moving average minus 1, minus that gap's own 10-year mean
  (multpl.com's monthly CAPE).
- fomc: the FOMC's median longer-run federal funds rate and the median for each year of its projections (FRED
  FEDTARMDLR, FEDTARMD).
- fiscal: nominal GDP growth on a year, federal interest payments and federal debt as % of GDP (FRED GDP,
  A091RC1Q027SBEA, GFDEGDQ188S).
- fedlong: the Fed's total assets and reserve balances, month ends since 2003 (FRED WALCL, WRESBAL; millions),
  the Treasury General Account (WTREGEN) and M2 (M2SL, billions, monthly).
- jp: the 10-year JGB yield (Ministry of Finance, daily; monthly averages since 1990, daily rows for 3 years) and
  Japan's overnight call rate (FRED IRSTCI01JPM156N, monthly).
- gold, dxy, btc: month-end prices (CNBC's chart service, full history) and US CPI (FRED CPIAUCSL) for gold in
  today's dollars.
FRED answers GitHub's runners only without a browser User-Agent; the others need one. A part that fails keeps its
previous value. Runs at most every 3 hours unless --force.
"""
import csv
import io
import json
import re
import statistics
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "money.json"
SPX = Path(__file__).resolve().parent.parent / "data" / "spx_history.csv"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TREAS = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
         "?type={t}&field_tdr_date_value={y}&page&_format=csv")
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}&cosd={d}"
CNBC = "https://ts-api.cnbc.com/harmony/app/charts/ALL.json?symbol={s}"
LOG = []


def log(*a):
    LOG.append(" ".join(str(x) for x in a))
    print(*a, file=sys.stderr)


def fnum(v):
    v = (v or "").strip().replace(",", "")
    if not v or v in (".", "-") or v.upper() == "N/A":
        return None
    try:
        return float(v)
    except ValueError:
        return None


# ---------- Treasury curves ----------
def treas_year(y, kind):
    t = "daily_treasury_yield_curve" if kind == "n" else "daily_treasury_real_yield_curve"
    r = requests.get(TREAS.format(y=y, t=t), headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    cols = {"n": [("2 Yr", "n2"), ("10 Yr", "n10"), ("30 Yr", "n30")],
            "r": [("5 YR", "r5"), ("10 YR", "r10"), ("30 YR", "r30")]}[kind]
    out = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        d = datetime.strptime(row["Date"], "%m/%d/%Y").strftime("%Y%m%d")
        out[d] = {k: fnum(row.get(c)) for c, k in cols}
    return out


def real_part(old, today):
    KEYS = ["n2", "n10", "n30", "r5", "r10", "r30"]
    rows = {r[0]: dict(zip(KEYS, r[1:])) for r in (old or {}).get("all", [])}
    have = {d[:4] for d in rows}
    years = [y for y in range(2003, today.year + 1)
             if str(y) not in have or y == today.year or (today.month == 1 and y == today.year - 1)]
    for y in years:
        for kind in ("n", "r"):
            try:
                for d, v in treas_year(y, kind).items():
                    rows.setdefault(d, {k: None for k in KEYS}).update(v)
            except Exception as e:
                log(f"treasury {kind} {y}: {e}")
    days = sorted(d for d, v in rows.items() if v.get("r10") is not None and v.get("n10") is not None)
    allrows = [[d] + [rows[d].get(k) for k in KEYS] for d in days]
    # monthly averages: [YYYY-MM, n10, r10, r30, be10(= n10 - r10), n2, r5]
    mon = {}
    for d in days:
        mon.setdefault(f"{d[:4]}-{d[4:6]}", []).append(rows[d])
    monthly = []
    for m, L in sorted(mon.items()):
        av = lambda k: round(statistics.mean([x[k] for x in L if x.get(k) is not None]), 3) \
            if any(x.get(k) is not None for x in L) else None
        n10, r10 = av("n10"), av("r10")
        monthly.append([m, n10, r10, av("r30"), round(n10 - r10, 3) if n10 is not None and r10 is not None else None,
                        av("n2"), av("r5")])
    return {"all": allrows, "monthly": monthly, "keys": ["date"] + KEYS}


# ---------- gravity and CAPE gap ----------
def spx_month_ends():
    out = {}
    with open(SPX) as f:
        for row in csv.DictReader(f):
            m, d, y = row["DATE"].split("/")
            v = fnum(row["CLOSE"])
            if v:
                out[f"{y}-{m}"] = v  # file is in date order: the last day of each month wins
    return out


def gravity(monthly):
    spx = spx_month_ends()
    ms = [r[0] for r in monthly if r[2] is not None]
    rv = {r[0]: r[2] for r in monthly if r[2] is not None}
    out, devs = [], []
    for i, m in enumerate(ms):
        ma = statistics.mean(rv[x] for x in ms[i - 119:i + 1]) if i >= 119 else None
        dev = rv[m] - ma if ma is not None else None
        g = sd = None
        if dev is not None:
            devs.append(dev)
            win = devs[-120:]
            if len(win) >= 24:
                sd = statistics.pstdev(win)
                g = dev / sd if sd else None
        y, mo = map(int, m.split("-"))
        f12 = f"{y + 1}-{mo:02d}"
        s0, s12 = spx.get(m), spx.get(f12)
        out.append([m, rv[m], None if ma is None else round(ma, 3), None if dev is None else round(dev, 3),
                    None if sd is None else round(sd, 3), None if g is None else round(g, 3),
                    s0, None if not (s0 and s12) else round((s12 / s0 - 1) * 100, 2)])
    return out


def multpl_cape():
    html = requests.get("https://www.multpl.com/shiller-pe/table/by-month", headers={"User-Agent": UA}, timeout=60).text
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>|&[#\w]+;", " ", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 2:
            continue
        m = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", cells[0])
        v = re.search(r"\d[\d,]*\.?\d*", cells[1])
        if m and v:
            dt = datetime.strptime(m.group(0), "%b %d, %Y")
            out.setdefault(f"{dt.year}-{dt.month:02d}", float(v.group(0).replace(",", "")))
    if len(out) < 600:
        raise RuntimeError(f"multpl: only {len(out)} months")
    return out


def cape_gap():
    c = multpl_cape()
    ms = sorted(c)[:-1]  # the newest row is the live estimate
    gap = {}
    for i, m in enumerate(ms):
        if i >= 119:
            gap[m] = c[m] / statistics.mean(c[x] for x in ms[i - 119:i + 1]) - 1
    gm = sorted(gap)
    out = []
    for i, m in enumerate(gm):
        if i >= 119:
            adj = gap[m] - statistics.mean(gap[x] for x in gm[i - 119:i + 1])
            if m >= "2000-01":
                out.append([m, c[m], round(gap[m] * 100, 2), round(adj * 100, 2)])
    return out


# ---------- FRED ----------
def fred(sid, since="1990-01-01"):
    r = requests.get(FRED.format(id=sid, d=since), timeout=(10, 60))
    r.raise_for_status()
    text = r.text
    if r.content[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(r.content))
        text = next(z.read(n).decode() for n in z.namelist() if n.endswith(".csv") and "README" not in n)
    out = []
    for row in csv.reader(io.StringIO(text)):
        if not row or not re.match(r"\d{4}-\d\d-\d\d", row[0]):
            continue
        v = fnum(row[1]) if len(row) > 1 else None
        if v is not None:
            out.append([row[0], v])
    if not out:
        raise RuntimeError(f"FRED {sid}: no rows")
    return out


def month_end(rows, scale=1):
    m = {}
    for d, v in rows:
        m[d[:7]] = round(v * scale, 3)
    return [[k, v] for k, v in sorted(m.items())]


def qkey(d):
    y, mo = int(d[:4]), int(d[5:7])
    return f"{y}-Q{(mo - 1) // 3 + 1}"


def fiscal():
    gdp = fred("GDP", "1980-01-01")
    g = {qkey(d): v for d, v in gdp}
    ks = sorted(g)
    ngdp = []
    for i, k in enumerate(ks):
        if i >= 4:
            ngdp.append([k, round((g[k] / g[ks[i - 4]] - 1) * 100, 2)])
    intr = [[qkey(d), round(v / g[qkey(d)] * 100, 2)] for d, v in fred("A091RC1Q027SBEA", "1980-01-01") if qkey(d) in g]
    debt = [[qkey(d), round(v, 1)] for d, v in fred("GFDEGDQ188S", "1980-01-01")]
    return {"ngdp": ngdp, "interest": intr, "debt": debt}


def fomc():
    lr = fred("FEDTARMDLR", "2012-01-01")
    md = fred("FEDTARMD", "2012-01-01")
    return {"lr": lr, "median": md}


def fedlong():
    tot = month_end(fred("WALCL", "2003-01-01"))
    res = month_end(fred("WRESBAL", "2003-01-01"))
    tga = month_end(fred("WTREGEN", "2003-01-01"))
    m2 = [[d[:7], v] for d, v in fred("M2SL", "1990-01-01")]
    return {"total": tot, "reserves": res, "tga": tga, "m2": m2}


# ---------- Japan ----------
def era(s):
    m = re.match(r"([SHR])(\d+)\.(\d+)\.(\d+)", s.strip())
    if not m:
        return None
    base = {"S": 1925, "H": 1988, "R": 2018}[m.group(1)]
    return date(base + int(m.group(2)), int(m.group(3)), int(m.group(4)))


def jgb_rows(url):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=90)
    r.raise_for_status()
    text = r.content.decode("shift_jis", errors="replace")
    out = {}
    lines = list(csv.reader(io.StringIO(text)))
    hdr = next((i for i, l in enumerate(lines) if len(l) > 10 and "10" in l[10]), 1)
    for l in lines[hdr + 1:]:
        if len(l) > 10:
            d = era(l[0])
            v = fnum(l[10])
            if d and v is not None:
                out[d.strftime("%Y%m%d")] = v
    return out


def japan(old):
    rows = {}
    try:
        rows.update(jgb_rows("https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv"))
    except Exception as e:
        log(f"jgb all: {e}")
        for d, v in (old or {}).get("jgb10d", []):
            rows[d] = v
        for m, v in (old or {}).get("jgb10m", []):
            pass
    try:
        rows.update(jgb_rows("https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"))
    except Exception as e:
        log(f"jgb current: {e}")
    if not rows:
        raise RuntimeError("no JGB rows")
    days = sorted(rows)
    mon = {}
    for d in days:
        if d >= "19900101":
            mon.setdefault(f"{d[:4]}-{d[4:6]}", []).append(rows[d])
    jm = [[m, round(statistics.mean(L), 3)] for m, L in sorted(mon.items())]
    if old and old.get("jgb10m") and len(jm) < len(old["jgb10m"]):
        jm = old["jgb10m"]
    cut = (date.today() - timedelta(days=3 * 365)).strftime("%Y%m%d")
    call = [[d[:7], v] for d, v in fred("IRSTCI01JPM156N", "1990-01-01")]
    return {"jgb10d": [[d, rows[d]] for d in days if d >= cut], "jgb10m": jm, "call": call}


# ---------- yardsticks ----------
def cnbc_monthly(sym):
    r = requests.get(CNBC.format(s=requests.utils.quote(sym)), headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    bars = r.json()["barData"]["priceBars"]
    m = {}
    for b in bars:
        t, c = b.get("tradeTime", ""), fnum(b.get("close"))
        if len(t) >= 8 and c:
            m[f"{t[:4]}-{t[4:6]}"] = c
    if len(m) < 60:
        raise RuntimeError(f"CNBC {sym}: only {len(m)} months")
    return [[k, v] for k, v in sorted(m.items())]


def main():
    force = "--force" in sys.argv
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    now = datetime.now(timezone.utc)
    if not force and old.get("updatedAt"):
        last = datetime.fromisoformat(old["updatedAt"].replace("Z", "+00:00"))
        if now - last < timedelta(hours=3):
            return
    today = date.today()
    out = dict(old)
    parts = [
        ("real", lambda: real_part(old.get("real"), today)),
        ("fomc", fomc),
        ("fiscal", fiscal),
        ("fedlong", fedlong),
        ("jp", lambda: japan(old.get("jp"))),
        ("gold", lambda: cnbc_monthly("@GC.1")),
        ("dxy", lambda: cnbc_monthly(".DXY")),
        ("btc", lambda: cnbc_monthly("BTC.CM=")),
        ("cpi", lambda: [[d[:7], v] for d, v in fred("CPIAUCSL", "1980-01-01")]),
        ("cape", cape_gap),
    ]
    for k, fn in parts:
        try:
            out[k] = fn()
        except Exception as e:
            log(f"{k}: {e}")
    if out.get("real"):
        try:
            out["gravity"] = gravity(out["real"]["monthly"])
        except Exception as e:
            log(f"gravity: {e}")
    out["halvings"] = ["2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20"]
    out["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    out["log"] = LOG[-20:]
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
