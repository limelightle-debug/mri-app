"""US economic releases for the institute's paper: data/macro.json.

- bls: the Bureau of Labor Statistics public API (v1, no key): payrolls (level, thousands), the unemployment rate,
  CPI and core CPI (not seasonally adjusted, for the change on a year; seasonally adjusted, for the month),
  PPI final demand and core, the JOLTS job openings rate. Months as "YYYY-MM".
- pce: the PCE price index and core (excluding food and energy) from BEA's monthly flat file (NipaDataM.txt).
- claims: weekly initial and continued jobless claims from the Labor Department.

FRED times out from GitHub's runners, so the sources are the agencies' own. Each is read at most every 3 hours
(the BLS key-less API allows 25 requests a day); the time of each read is kept outside the repo. A failed source
keeps its last good data. Writes the file only when something changed.
"""
import csv
import io
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "macro.json"
CHECKED = Path("/tmp/macro_checked.json")
DEBUG = Path("/tmp/macro_debug")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
EVERY = timedelta(hours=3)

BLS = {
    "CES0000000001": "payrolls",      # all employees, total nonfarm, SA, thousands
    "LNS14000000": "unrate",          # unemployment rate, SA
    "CUUR0000SA0": "cpi",             # CPI-U all items, NSA
    "CUUR0000SA0L1E": "core_cpi",     # CPI-U less food and energy, NSA
    "CUSR0000SA0": "cpi_sa",
    "CUSR0000SA0L1E": "core_cpi_sa",
    "WPUFD4": "ppi",                  # PPI final demand, NSA
    "WPUFD49104": "core_ppi",         # final demand less foods, energy and trade services, NSA
    "WPSFD4": "ppi_sa",
    "JTS000000000000000JOR": "jolts", # job openings rate, SA
}
PCE = {"DPCERG": "pce", "DPCCRG": "core_pce"}


def bls():
    y = date.today().year
    r = requests.post("https://api.bls.gov/publicAPI/v1/timeseries/data/",
                      json={"seriesid": list(BLS), "startyear": str(y - 4), "endyear": str(y)},
                      headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError(f"BLS: {j.get('status')} {j.get('message')}")
    out = {}
    for s in j["Results"]["series"]:
        rows = sorted([f"{d['year']}-{d['period'][1:]}", float(d["value"])] for d in s["data"]
                      if d["period"].startswith("M") and d["period"] != "M13" and d["value"] not in ("-", ""))
        if rows:
            out[BLS[s["seriesID"]]] = rows
    if "cpi" not in out or "payrolls" not in out:
        raise ValueError("BLS: payrolls or CPI missing")
    return out


def pce():
    r = requests.get("https://apps.bea.gov/national/Release/TXT/NipaDataM.txt", headers={"User-Agent": UA}, timeout=120)
    r.raise_for_status()
    out = {v: [] for v in PCE.values()}
    start = f"{date.today().year - 4}M01"
    for line in r.text.splitlines():
        code = line.split(",", 1)[0]
        if code in PCE:
            c, per, val = next(csv.reader([line]))
            if per >= start:
                out[PCE[c]].append([f"{per[:4]}-{per[5:]}", float(val.replace(",", ""))])
    if not out["pce"]:
        raise ValueError("PCE: no DPCERG rows")
    if not out["core_pce"]:
        print("PCE: no DPCCRG rows (core)", file=sys.stderr)
        del out["core_pce"]
    return {k: sorted(v) for k, v in out.items()}


def claims():
    """National weekly claims (seasonally adjusted) from the Labor Department's weekly claims report."""
    y = date.today().year
    url = "https://oui.doleta.gov/unemploy/wkclaims/report.asp"
    form = {"level": "nation", "strtdate": str(y - 3), "enddate": str(y), "filetype": "csv", "final": "Submit"}
    r = requests.post(url, data=form, headers={"User-Agent": UA, "Referer": "https://oui.doleta.gov/unemploy/claims.asp"},
                      timeout=60)
    r.raise_for_status()
    DEBUG.mkdir(exist_ok=True)
    (DEBUG / "claims.txt").write_text(r.text[:20000])
    rows = list(csv.reader(io.StringIO(r.text)))
    head = next((i for i, x in enumerate(rows) if any("Week" in c for c in x)), None)
    if head is None:
        raise ValueError(f"claims: no header in {r.text[:200]!r}")
    cols = [c.strip().lower() for c in rows[head]]

    def col(*names):
        for i, c in enumerate(cols):
            if all(n in c for n in names):
                return i
        raise ValueError(f"claims: no column {names} in {cols}")
    iw, iic, icc = col("week"), col("initial", "sa"), col("continued", "sa")
    if "nsa" in cols[iic]:
        iic = next(i for i, c in enumerate(cols) if "initial" in c and "sa" in c and "nsa" not in c)
    if "nsa" in cols[icc]:
        icc = next(i for i, c in enumerate(cols) if "continued" in c and "sa" in c and "nsa" not in c)
    out = []
    for x in rows[head + 1:]:
        if len(x) <= max(iw, iic, icc):
            continue
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", x[iw].strip())
        if not m:
            continue
        num = lambda s: float(s.replace(",", "")) if s.strip().replace(",", "").replace(".", "").isdigit() else None
        out.append([f"{m[3]}-{int(m[1]):02d}-{int(m[2]):02d}", num(x[iic]), num(x[icc])])
    if not out:
        raise ValueError("claims: no rows")
    return sorted(out)


def main():
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    now = datetime.now(timezone.utc)
    try:
        checked = json.loads(CHECKED.read_text())
    except (OSError, ValueError):
        checked = {}
    force = "--force" in sys.argv
    out = {k: old[k] for k in ("bls", "pce", "claims") if k in old}
    for k, f in (("bls", bls), ("pce", pce), ("claims", claims)):
        last = checked.get(k)
        if not force and last and now - datetime.fromisoformat(last) < EVERY and k in out:
            continue
        checked[k] = now.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        try:
            out[k] = f()
        except Exception as e:  # noqa: BLE001  (one bad source must not stop the rest)
            print(f"{k}: {e}", file=sys.stderr)
    CHECKED.write_text(json.dumps(checked))
    if not out:
        sys.exit(1)
    if all(old.get(k) == out.get(k) for k in ("bls", "pce", "claims")):
        return
    out["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print({k: (sorted(out[k]) if isinstance(out[k], dict) else len(out[k])) for k in out if k != "updatedAt"})


if __name__ == "__main__":
    main()
