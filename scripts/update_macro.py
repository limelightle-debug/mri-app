"""US economic releases for the institute's paper: data/macro.json.

- bls: the Bureau of Labor Statistics public API (v1, no key): payrolls (level, thousands), the unemployment rate,
  CPI and core CPI (not seasonally adjusted, for the change on a year; seasonally adjusted, for the month),
  PPI final demand and core, the JOLTS job openings rate. Months as "YYYY-MM".
- pce: the PCE price index and core (excluding food and energy) from BEA's monthly flat file (NipaDataM.txt).
- claims: weekly initial and continued jobless claims from the Labor Department.
- gdp: real GDP, percent change at an annual rate, quarterly (BEA's NipaDataQ.txt, A191RL).
- gdpnow: the Atlanta Fed's GDPNow for the quarter being tracked, each update (its workbook's CurrentQtrEvolution
  sheet), and the track record (the last nowcast before BEA's advance estimate, and that estimate).

FRED times out from GitHub's runners, so the sources are the agencies' own. Each is read at most every 3 hours
(the BLS key-less API allows 25 requests a day); the time of each read is kept outside the repo. A failed source
keeps its last good data. Writes the file only when something changed.
"""
import csv
import html
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
                      json={"seriesid": list(BLS), "startyear": str(y - 9), "endyear": str(y)},  # 10 years (the key-less limit)
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


def gdp():
    r = requests.get("https://apps.bea.gov/national/Release/TXT/NipaDataQ.txt", headers={"User-Agent": UA}, timeout=120)
    r.raise_for_status()
    out = []
    for line in r.text.splitlines():
        if line.startswith("A191RL,"):
            _, per, val = next(csv.reader([line]))
            if per >= "2015Q1":
                out.append([per[:4] + "-" + per[4:], float(val.replace(",", ""))])
    if not out:
        raise ValueError("GDP: no A191RL rows")
    return sorted(out)


def gdpnow():
    try:
        import openpyxl
    except ImportError:  # a loop started before the workflow installed it
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "openpyxl"], check=True, timeout=120)
        import openpyxl
    r = requests.get("https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/research-and-data/data/gdpnow/"
                     "GDPTrackingModelDataAndForecasts.xlsx", headers={"User-Agent": UA}, timeout=120)
    r.raise_for_status()
    wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)
    evo, quarter = [], None
    for row in wb["CurrentQtrEvolution"].iter_rows(min_row=2, values_only=True):
        for i in range(0, len(row) - 2, 3):  # side by side blocks of (date, releases, GDP)
            d, rel, v = row[i:i + 3]
            if isinstance(d, datetime) and isinstance(v, (int, float)):
                evo.append([d.strftime("%Y-%m-%d"), round(v, 2), str(rel or "").strip()])
                m = re.search(r"(\d\d):Q([1-4])", str(rel or ""))
                if m and "Initial" in str(rel):
                    quarter = f"20{m[1]}-Q{m[2]}"
    if not evo:
        raise ValueError("GDPNow: no evolution rows")
    evo.sort()
    track = []
    for row in wb["TrackRecord"].iter_rows(min_row=2, values_only=True):
        q, now, adv = row[:3]
        if isinstance(q, datetime) and isinstance(now, (int, float)) and isinstance(adv, (int, float)):
            track.append([f"{q.year}-Q{(q.month - 1) // 3 + 1}", round(now, 2), round(adv, 2)])
    if not quarter:  # the quarter after the last one in the track record
        y, qn = map(int, sorted(track)[-1][0].split("-Q")) if track else (date.today().year, 0)
        quarter = f"{y + qn // 4}-Q{qn % 4 + 1}"
    return {"quarter": quarter, "evo": evo, "track": sorted(track)[-16:]}


def claims():
    """National weekly claims from the Labor Department's weekly claims report (r539cy, an HTML table): rows of
    week, initial claims NSA, seasonal factor, SA, SA 4-week average, continued claims NSA, factor, SA, SA 4-week,
    insured unemployment rate NSA and SA, covered employment. Keeps [week, initial SA, continued SA]."""
    y = date.today().year
    form = {"level": "nation", "strtdate": str(y - 3), "enddate": str(y), "filetype": "html", "final": "Submit"}
    r = requests.post("https://oui.doleta.gov/unemploy/wkclaims/report.asp", data=form,
                      headers={"User-Agent": UA, "Referer": "https://oui.doleta.gov/unemploy/claims.asp"}, timeout=60)
    r.raise_for_status()
    rows = {}
    for d, k, v in re.findall(r'<td headers="(\d\d/\d\d/\d{4}) (\w+)"[^>]*>([^<]*)', r.text):
        rows.setdefault(d, {})[k] = v.strip().replace(",", "")
    num = lambda v: float(v) if v and re.fullmatch(r"\d+(\.\d+)?", v) else None
    out = []
    for d, x in rows.items():
        ic = num(x.get("sa_initial_claims"))
        if ic:
            out.append([f"{d[6:]}-{d[:2]}-{d[3:5]}", ic, num(x.get("sa_continued_claims"))])
    if not out:
        DEBUG.mkdir(exist_ok=True)
        (DEBUG / "claims.txt").write_text(r.text[:20000])
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
    KEYS = ("bls", "pce", "claims", "gdp", "gdpnow")
    out = {k: old[k] for k in KEYS if k in old}
    for k, f in (("bls", bls), ("pce", pce), ("claims", claims), ("gdp", gdp), ("gdpnow", gdpnow)):
        last = checked.get(k)
        short = k == "bls" and len((out.get("bls") or {}).get("jolts", [])) < 100  # ten years wanted (Beveridge curve)
        if not force and not short and last and now - datetime.fromisoformat(last) < EVERY and k in out:
            continue
        checked[k] = now.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        try:
            out[k] = f()
        except Exception as e:  # noqa: BLE001  (one bad source must not stop the rest)
            print(f"{k}: {e}", file=sys.stderr)
    CHECKED.write_text(json.dumps(checked))
    if not out:
        sys.exit(1)
    if all(old.get(k) == out.get(k) for k in KEYS):
        return
    out["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print({k: (sorted(out[k]) if isinstance(out[k], dict) else len(out[k])) for k in out if k != "updatedAt"})


if __name__ == "__main__":
    main()
