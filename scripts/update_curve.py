"""The US Treasury yield curve for the institute's morning paper: data/curve.json.

Source: the Treasury's daily par yield curve (home.treasury.gov), 1 month to 30 years. Keeps the latest
day's curve, the curves 3 and 6 months earlier, and the 10Y-2Y and 10Y-3M spreads day by day for the last 5 years.
Also, each with its value 3 months earlier:
- infl: the 10-year real yield (the Treasury's daily par real yield curve) and the 10-year breakeven inflation,
  the nominal 10-year par yield minus the real one (as FRED's T10YIE: DGS10 - DFII10)
  (with the real yield day by day for 5 years)
- oas: the ICE BofA option-adjusted spreads of US high yield and investment grade corporate bonds (FRED
  BAMLH0A0HYM2, BAMLC0A0CM; posted a day later), with high yield day by day for the 3 years FRED keeps
Either of those failing leaves it out (the curve still updates). Writes only when something changes.
"""
import csv
import io
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "curve.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
       "?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
REAL_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
            "?type=daily_treasury_real_yield_curve&field_tdr_date_value={y}&page&_format=csv")
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2,BAMLC0A0CM&cosd={d}"
TENORS = [("1 Mo", "1M", 1 / 12), ("3 Mo", "3M", .25), ("6 Mo", "6M", .5), ("1 Yr", "1Y", 1), ("2 Yr", "2Y", 2),
          ("3 Yr", "3Y", 3), ("5 Yr", "5Y", 5), ("7 Yr", "7Y", 7), ("10 Yr", "10Y", 10), ("20 Yr", "20Y", 20),
          ("30 Yr", "30Y", 30)]


def year_rows(y):
    r = requests.get(URL.format(y=y), headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    out = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        d = datetime.strptime(row["Date"], "%m/%d/%Y").date()
        vals = {}
        for col, k, _ in TENORS:
            v = (row.get(col) or "").strip()
            if v and v.upper() != "N/A":
                vals[k] = float(v)
        if "2Y" in vals and "10Y" in vals:
            out[d] = vals
    return out


def real10(y):
    r = requests.get(REAL_URL.format(y=y), headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    out = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        v = (row.get("10 YR") or "").strip()
        if v and v.upper() != "N/A":
            out[datetime.strptime(row["Date"], "%m/%d/%Y").date()] = float(v)
    return out


def with_m3(series, keys):
    """{date: (v1, v2)} -> the latest day's values, the day before's (_d1) and those on or before 3 months earlier."""
    days = sorted(series)
    last = days[-1]
    d1 = series[days[-2]] if len(days) > 1 else None
    prev = [d for d in days if d <= last - timedelta(days=91)]
    m3 = series[prev[-1]] if prev else None
    out = {"date": last.isoformat()}
    for i, k in enumerate(keys):
        out[k] = series[last][i]
        out[k + "_m3"] = m3[i] if m3 else None
        out[k + "_d1"] = d1[i] if d1 else None
    return out


def infl(rows, today, old):
    # the 10-year real yield day by day for 5 years ("hist", for the chart): kept from the last run, so only the
    # current year (and the last one in January) is downloaded again
    hist = {datetime.strptime(d, "%Y%m%d").date(): v for d, v in (old or {}).get("hist", [])}
    first = today.year - 5 if not hist else (today.year - 1 if today.month == 1 else today.year)
    real = {}
    for y in range(first, today.year + 1):
        real.update(real10(y))
    if not real:
        raise ValueError("no 10-year real yields (column '10 YR')")
    hist.update(real)
    s = {d: (v, round(rows[d]["10Y"] - v, 2)) for d, v in hist.items() if d in rows}
    if not s:
        return None
    out = with_m3(s, ["real10", "be10"])
    start = today - timedelta(days=5 * 365 + 2)
    out["hist"] = [[d.strftime("%Y%m%d"), v] for d, v in sorted(hist.items()) if d >= start]
    return out


def oas(today, old):
    # FRED is slow from GitHub's runners at times: short timeouts, two tries, and at most one check an hour
    # (the series moves once a day); between checks the last values stay
    now = datetime.now(timezone.utc)
    if old and old.get("checked") and now - datetime.fromisoformat(old["checked"]) < timedelta(hours=1):
        return old
    r = None
    for _ in range(2):
        try:
            r = requests.get(FRED.format(d=(today - timedelta(days=3 * 365)).isoformat()), headers={"User-Agent": UA},
                             timeout=(10, 45))
            break
        except requests.RequestException as e:
            err = e
    if r is None:
        raise err
    r.raise_for_status()
    s = {}
    for row in csv.reader(io.StringIO(r.text)):
        if not row or not row[0][:1].isdigit():
            continue
        try:
            s[date.fromisoformat(row[0])] = (float(row[1]), float(row[2]))
        except ValueError:  # "." or empty on holidays
            continue
    if not s:
        return None
    out = with_m3(s, ["hy", "ig"])
    # high yield OAS day by day ("hist", for the chart; FRED keeps 3 years of the ICE series)
    out["hist"] = [[d.strftime("%Y%m%d"), v[0]] for d, v in sorted(s.items())]
    out["checked"] = now.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    return out


def main():
    today = date.today()
    rows = {}
    for y in range(today.year - 5, today.year + 1):
        try:
            rows.update(year_rows(y))
        except Exception as e:  # noqa: BLE001  (an old year failing must not stop the rest)
            print(f"{y}: {e}", file=sys.stderr)
    if not rows:
        sys.exit("no curve data")
    days = sorted(rows)
    last = days[-1]
    old = json.loads(OUT.read_text()) if OUT.exists() else {}

    def on_or_before(d):
        c = [x for x in days if x <= d]
        return c[-1] if c else days[0]

    snap = lambda d: {"date": d.isoformat(), "y": rows[d]}
    out = {
        "date": last.isoformat(),
        "tenors": [[k, yrs] for _, k, yrs in TENORS],
        "now": snap(last),
        "prev": snap(days[-2]),  # the day before, for the day's changes
        "m3": snap(on_or_before(last - timedelta(days=91))),
        "m6": snap(on_or_before(last - timedelta(days=182))),
        # day by day: [date, 10Y-2Y, 10Y-3M]
        "spread": [[d.strftime("%Y%m%d"), round(rows[d]["10Y"] - rows[d]["2Y"], 2),
                    round(rows[d]["10Y"] - rows[d]["3M"], 2) if "3M" in rows[d] else None] for d in days],
        "source": "U.S. Treasury daily par yield curve",
    }
    for k, f in (("infl", lambda: infl(rows, today, old.get("infl"))), ("oas", lambda: oas(today, old.get("oas")))):
        try:
            v = f()
        except Exception as e:  # noqa: BLE001
            print(f"{k}: {e}", file=sys.stderr)
            v = old.get(k)  # keep the last good one
            if k == "oas" and v:  # a failed try also waits an hour, so timeouts do not slow every pass
                v = dict(v, checked=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"))
        if v:
            out[k] = v
    if {k: v for k, v in old.items() if k != "updatedAt"} == out:
        return
    out["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(last, rows[last])


if __name__ == "__main__":
    main()
