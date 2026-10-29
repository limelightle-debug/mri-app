"""Dollar liquidity for the institute's paper: data/liquidity.json.

- fed: the Fed's H.4.1 release (weekly, Thursday 4:30 pm ET). Total assets (Wednesday level, the consolidated
  statement) and reserve balances with the Reserve Banks (week average), with the changes the release prints
  from the week before and from a year before. Millions of dollars.
- rrp: the overnight reverse repo facility, the New York Fed's daily operation results (amount accepted).
- m2: M2 from the H.6 release (monthly, seasonally adjusted, billions of dollars).

FRED times out from GitHub's runners, so the sources are the Fed's own pages. Each source is read at most once an
hour (the time of each read is kept outside the repo, so a check alone makes no commit); a failed one keeps the
last good value. Writes the file only when something changed.
"""
import html
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "liquidity.json"
CHECKED = Path("/tmp/liquidity_checked.json")  # lives as long as the workflow job
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MON = {m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "June", "July", "Aug", "Sept", "Oct", "Nov", "Dec"])}
MON.update({"Jun": 6, "Jul": 7, "Sep": 9})


def get(url):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    return r.text


def text(page):
    t = html.unescape(re.sub(r"<[^>]+>", " ", page))
    return re.sub(r"\s+", " ", t)


def n(s):
    s = s.replace(" ", "").replace(",", "")
    return 0 if s in ("0", "+0", "-0") else int(s)


CHG = r"([+-]\s*[\d,]+|0)"


def fed():
    t = text(get("https://www.federalreserve.gov/releases/h41/current/"))
    m = re.search(r"Week ended (\w+)\.? (\d+), (\d{4})", t)
    if not m:
        raise ValueError("no week in H.4.1")
    week = date(int(m[3]), MON[m[1]], int(m[2])).isoformat()
    out = {"week": week}
    for k, pat in (("total", r"Total assets \(\d+\) ([\d,]+) " + CHG + " " + CHG),
                   ("reserves", r"Reserve balances with Federal Reserve Banks ([\d,]+) " + CHG + " " + CHG)):
        x = re.search(pat, t)
        if not x:
            raise ValueError(f"no {k} in H.4.1")
        out[k] = [n(x[1]), n(x[2]), n(x[3])]  # level, change from the week before, from a year before
    return out


def rrp(old):
    start = (date.today() - timedelta(days=400)).isoformat()
    j = json.loads(get(f"https://markets.newyorkfed.org/api/rp/reverserepo/propositions/search.json?startDate={start}"))
    days = {}
    for o in j.get("repo", {}).get("operations", []):
        if o.get("operationType") == "Reverse Repo" and o.get("totalAmtAccepted") is not None:
            d = o["operationDate"]
            days[d] = days.get(d, 0) + o["totalAmtAccepted"]  # a day with two operations counts both
    if not days:
        raise ValueError("no reverse repo operations")
    hist = sorted([d, round(v / 1e9, 3)] for d, v in days.items())
    return {"date": hist[-1][0], "hist": hist}  # billions of dollars


def m2():
    t = text(get("https://www.federalreserve.gov/releases/h6/current/default.htm"))
    t = t[t.find("Table 1"):]
    rows = re.findall(r"(Jan|Feb|Mar|Apr|May|June|July|Aug|Sept|Oct|Nov|Dec)\.? (\d{4}) ([\d,.]+) ([\d,.]+)", t)
    hist, seen = [], set()
    for mo, yr, _m1, v in rows:
        ym = f"{yr}-{MON[mo]:02d}"
        if ym in seen:
            break  # the first table only
        seen.add(ym)
        hist.append([ym, float(v.replace(",", ""))])
    if len(hist) < 13:
        raise ValueError("M2: under 13 months")
    return {"month": hist[-1][0], "hist": hist}


def main():
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    now = datetime.now(timezone.utc)
    try:
        checked = json.loads(CHECKED.read_text())
    except (OSError, ValueError):
        checked = {}
    out = {k: old[k] for k in ("fed", "rrp", "m2") if k in old}
    for k, f in (("fed", fed), ("rrp", lambda: rrp(old.get("rrp"))), ("m2", m2)):
        last = checked.get(k)
        if last and now - datetime.fromisoformat(last) < timedelta(hours=1) and k in out:
            continue
        checked[k] = now.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        try:
            out[k] = f()
        except Exception as e:  # noqa: BLE001  (one bad source must not stop the rest)
            print(f"{k}: {e}", file=sys.stderr)
    CHECKED.write_text(json.dumps(checked))
    if not out:
        sys.exit(1)
    if all(old.get(k) == out.get(k) for k in ("fed", "rrp", "m2")):
        return
    out["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print({k: (out[k].get("week") or out[k].get("date") or out[k].get("month")) for k in ("fed", "rrp", "m2") if k in out})


if __name__ == "__main__":
    main()
