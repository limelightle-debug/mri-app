"""One-off: two years of weekly Fed total assets and reserves from archived H.4.1 releases, and older M2 months
from an archived H.6, merged into data/liquidity.json (update_liquidity.py keeps them going from there)."""
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_liquidity as U  # noqa: E402

BASE = "https://www.federalreserve.gov/releases"


def try_get(url):
    try:
        return U.get(url)
    except Exception:  # noqa: BLE001
        return None


def main():
    d = json.loads(U.OUT.read_text()) if U.OUT.exists() else {}
    fed = d.get("fed") or {}
    hist = {h[0]: h for h in fed.get("hist", [])}
    # H.4.1 comes out on Thursdays (a day earlier or later around holidays)
    t = date.today()
    thu = t - timedelta(days=(t.weekday() - 3) % 7)
    have = set(hist)
    for w in range(int(sys.argv[1]) if len(sys.argv) > 1 else 110):
        day = thu - timedelta(weeks=w)
        if any(abs((date.fromisoformat(h) - day).days) <= 3 for h in have):
            continue  # that week is already there
        for off in (0, -1, 1, -2):
            page = try_get(f"{BASE}/h41/{(day + timedelta(days=off)).strftime('%Y%m%d')}/")
            if page and "Week ended" in page:
                break
        else:
            print("no H.4.1 near", day, file=sys.stderr)
            continue
        try:
            x = U.parse_h41(page)
        except ValueError as e:
            print(day, e, file=sys.stderr)
            continue
        hist[x["week"]] = [x["week"], x["total"][0], x["reserves"][0]]
    fed["hist"] = sorted(hist.values())
    d["fed"] = fed
    # M2: an H.6 from about a year ago carries the 17 months before the current table's
    idx = try_get(f"{BASE}/h6/") or ""
    links = sorted(set(re.findall(r"/releases/h6/(\d{8})/", idx)))
    print("H.6 archive links:", links[-30:], file=sys.stderr)
    m2 = {h[0]: h for h in (d.get("m2") or {}).get("hist", [])}
    for target in (365, 730):
        want = (t - timedelta(days=target)).strftime("%Y%m%d")
        cand = [l for l in links if l <= want]
        if not cand:
            continue
        page = try_get(f"{BASE}/h6/{cand[-1]}/default.htm") or try_get(f"{BASE}/h6/{cand[-1]}/")
        if page:
            for ym, v in U.parse_h6(page):
                m2.setdefault(ym, [ym, v])
    if m2:
        d.setdefault("m2", {})["hist"] = sorted(m2.values())
    U.OUT.write_text(json.dumps(d, separators=(",", ":")))
    print("fed weeks", len(fed["hist"]), "m2 months", len(m2))


if __name__ == "__main__":
    main()
