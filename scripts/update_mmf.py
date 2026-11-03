"""Money market funds for the institute's paper: data/mmf.json.

The OFR's U.S. Money Market Fund Monitor (SEC Form N-MFP, month-end holdings of every US money fund), from the OFR's
short-term funding API (no key; no browser User-Agent, like FRED). Monthly, published some days after the month ends.
  total     all money fund investments (MMF-MMF_TOT-M)
  treasury  in US Treasury securities, mostly bills (MMF-MMF_T_TOT-M)
  repo      in repurchase agreements, the Fed's overnight reverse repo included (MMF-MMF_RP_TOT-M)
hist: [["YYYY-MM", total, treasury, repo]] in billions of dollars. Read at most every 6 hours; a failed read keeps the
last good file. Writes only when something changed.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "mmf.json"
CHECKED = Path("/tmp/mmf_checked")
API = "https://data.financialresearch.gov/v1/series/timeseries"
SERIES = {"total": "MMF-MMF_TOT-M", "treasury": "MMF-MMF_T_TOT-M", "repo": "MMF-MMF_RP_TOT-M"}


def series(mn):
    r = requests.get(API, params={"mnemonic": mn}, timeout=60)
    r.raise_for_status()
    j = r.json()
    rows = j if isinstance(j, list) else (j.get("data") or j.get("timeseries") or j.get(mn) or [])
    if isinstance(rows, dict):
        rows = rows.get("aggregation") or rows.get("data") or list(rows.items())
    out = {}
    for row in rows:
        d, v = (row[0], row[1]) if isinstance(row, (list, tuple)) else (row.get("date"), row.get("value"))
        if d is None or v is None:
            continue
        out[str(d)[:7]] = float(v)
    return out


def main(force=False):
    if not force and CHECKED.exists() and time.time() - CHECKED.stat().st_mtime < 6 * 3600:
        return
    CHECKED.touch()
    try:
        S = {k: series(mn) for k, mn in SERIES.items()}
    except Exception as e:
        print("mmf: read failed:", e, file=sys.stderr)
        return
    if not S["total"]:
        print("mmf: no rows", file=sys.stderr)
        return
    # dollars to billions (the API gives dollars)
    sc = 1e9 if max(S["total"].values()) > 1e8 else 1.0
    v = lambda k, m: round(S[k][m] / sc, 1) if m in S[k] else None
    hist = [[m, v("total", m), v("treasury", m), v("repo", m)] for m in sorted(S["total"])]
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if old.get("hist") == hist:
        return
    OUT.write_text(json.dumps({"source": "OFR U.S. Money Market Fund Monitor (SEC Form N-MFP)", "unit": "billion USD",
                               "hist": hist, "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                              ensure_ascii=False, separators=(",", ":")))
    print("mmf:", hist[-1])


if __name__ == "__main__":
    main(force="--force" in sys.argv)
