"""One-off: fill the month-end real-time CAPE of past months in data/cape_vintage.json from the Internet Archive's
copies of multpl.com/shiller-pe ("Current Shiller PE Ratio: x"), as the page stood at each month's end.

For each month, the last copy taken from the month's last day up to the next month's 2nd day (the page shows the
previous close, so a copy on the 1st still carries the month-end value) is used; months without such a copy stay empty.
"""
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "data"
VF = DATA / "cape_vintage.json"
UA = {"User-Agent": "Mozilla/5.0 (research; mri-app cape vintage)"}


def cdx(url):
    r = requests.get("https://web.archive.org/cdx/search/cdx", params={
        "url": url, "output": "json", "fl": "timestamp,statuscode", "filter": "statuscode:200", "collapse": "timestamp:10"},
        headers=UA, timeout=120)
    r.raise_for_status()
    rows = r.json()
    return [x[0] for x in rows[1:]]


def value(ts, url):
    for k in range(3):
        try:
            r = requests.get(f"https://web.archive.org/web/{ts}id_/https://www.{url}", headers=UA, timeout=60)
            if r.status_code == 200:
                m = re.search(r"Current\s+Shiller\s+PE\s+Ratio[^0-9]{0,200}?(\d{1,2}\.\d{1,2})", re.sub(r"<[^>]+>", " ", r.text), re.S)
                return float(m.group(1)) if m else None
        except requests.RequestException:
            pass
        time.sleep(3 * (k + 1))
    return None


def main():
    v = json.loads(VF.read_text(encoding="utf-8"))
    rows = v.setdefault("rows", {})
    ts = cdx("multpl.com/shiller-pe")
    print(f"copies: {len(ts)} {ts[:1]} .. {ts[-1:]}")
    by = {}
    for t in ts:
        d = date(int(t[:4]), int(t[4:6]), int(t[6:8]))
        # a copy belongs to month m if taken on m's last 2 days or on the next month's first 2 days
        nxt = (d.replace(day=1) - timedelta(days=1)) if d.day <= 2 else None
        last = (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if d >= last - timedelta(days=1):
            by.setdefault(d.year * 100 + d.month, []).append((0, t))
        if nxt:
            by.setdefault(nxt.year * 100 + nxt.month, []).append((1, t))
    filled = 0
    for m in sorted(by):
        k = str(m)
        if rows.get(k, {}).get("rt") is not None and rows[k].get("rtSrc") != "wayback":
            continue  # this app's own record wins
        for _, t in sorted(by[m], reverse=True):  # the latest copy first (next month's 1st-2nd, then the month's end)
            x = value(t, "multpl.com/shiller-pe")
            time.sleep(1.5)
            if x:
                rows.setdefault(k, {}).update({"rt": x, "rtDate": t[:8], "rtSrc": "wayback"})
                filled += 1
                print(m, x, t)
                break
    v["rows"] = dict(sorted(rows.items()))
    VF.write_text(json.dumps(v, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"filled {filled} months")


if __name__ == "__main__":
    sys.exit(main())
