"""Dollar liquidity for the institute's paper: data/liquidity.json.

- fed: the Fed's H.4.1 release (weekly, Thursday 4:30 pm ET). Total assets (Wednesday level, the consolidated
  statement) and reserve balances with the Reserve Banks (week average), with the changes the release prints
  from the week before and from a year before. Millions of dollars.
- rrp: the overnight reverse repo facility, the New York Fed's daily operation results (amount accepted).
- m2: M2 from the H.6 release (monthly, seasonally adjusted, billions of dollars).
- money: the strain on the plumbing (『金利の重力』 第十七章). SOFR against the interest paid on reserves (IORB, the top
  of the target range less 0.10), day by day from the New York Fed; SOFR above IORB means cash is getting scarce.
  And the Fed's repo operations (the standing repo facility), the amount taken.

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


def parse_h41(page):
    t = text(page)
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


def fed(old):
    out = parse_h41(get("https://www.federalreserve.gov/releases/h41/current/"))
    # weekly history [week, total assets, reserves] (millions), two years
    hist = {h[0]: h for h in (old or {}).get("hist", [])}
    hist[out["week"]] = [out["week"], out["total"][0], out["reserves"][0]]
    out["hist"] = sorted(hist.values())[-300:]
    return out


def rrp(old):
    have = (old or {}).get("hist", [])
    start = "2021-01-01" if not have or have[0][0] > "2021-02-01" else (date.today() - timedelta(days=400)).isoformat()
    j = json.loads(get(f"https://markets.newyorkfed.org/api/rp/reverserepo/propositions/search.json?startDate={start}"))
    days = {}
    for o in j.get("repo", {}).get("operations", []):
        if o.get("operationType") == "Reverse Repo" and o.get("totalAmtAccepted") is not None:
            d = o["operationDate"]
            days[d] = days.get(d, 0) + o["totalAmtAccepted"]  # a day with two operations counts both
    if not days:
        raise ValueError("no reverse repo operations")
    keep = {h[0]: h[1] for h in (old or {}).get("hist", [])}
    keep.update({d: round(v / 1e9, 3) for d, v in days.items()})
    hist = sorted([d, v] for d, v in keep.items())[-1600:]
    return {"date": hist[-1][0], "hist": hist}  # billions of dollars


def nyfed(path):
    return json.loads(get("https://markets.newyorkfed.org/api/" + path))


def money(old):
    """SOFR less IORB by day (IORB = the day's target range top less 0.10, from the EFFR records), and repo
    operations taken (billions)."""
    start = (date.today() - timedelta(days=760)).isoformat()
    end = date.today().isoformat()
    sofr = {x["effectiveDate"]: float(x["percentRate"]) for x in
            nyfed(f"rates/secured/sofr/search.json?startDate={start}&endDate={end}").get("refRates", [])}
    top = {x["effectiveDate"]: float(x["targetRateTo"]) for x in
           nyfed(f"rates/unsecured/effr/search.json?startDate={start}&endDate={end}").get("refRates", [])
           if x.get("targetRateTo") is not None}
    if not sofr or not top:
        raise ValueError("SOFR or EFFR records missing")
    spread = [[d, round(sofr[d], 3), round(sofr[d] - (top[d] - 0.10), 3)] for d in sorted(sofr) if d in top]
    repo = {}
    for path in (f"rp/repo/all/results/search.json?startDate={start}&endDate={end}",
                 f"rp/repo/propositions/search.json?startDate={start}"):
        try:
            for o in nyfed(path).get("repo", {}).get("operations", []):
                if o.get("operationType") == "Repo" and o.get("totalAmtAccepted") is not None:
                    repo[o["operationDate"]] = repo.get(o["operationDate"], 0) + o["totalAmtAccepted"] / 1e9
            if repo:
                break
        except Exception as e:  # noqa: BLE001
            print("repo:", path, e, file=sys.stderr)
    return {"spread": spread, "repo": sorted([d, round(v, 3)] for d, v in repo.items())}


def parse_h6(page):
    t = text(page)
    t = t[t.find("Table 1"):]
    rows = re.findall(r"(Jan|Feb|Mar|Apr|May|June|July|Aug|Sept|Oct|Nov|Dec)\.? (\d{4}) ([\d,.]+) ([\d,.]+)", t)
    hist, seen = [], set()
    for mo, yr, _m1, v in rows:
        ym = f"{yr}-{MON[mo]:02d}"
        if ym in seen:
            break  # the first table only
        seen.add(ym)
        hist.append([ym, float(v.replace(",", ""))])
    return hist


def m2_history():
    """Monthly M2 (seasonally adjusted, billions) from the H.6 data package (FRB_h6_xml.zip, SDMX XML)."""
    import io
    import zipfile
    r = requests.get("https://www.federalreserve.gov/releases/h6/data/FRB_h6_xml.zip", headers={"User-Agent": UA}, timeout=120)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    xml = "".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.lower().endswith(".xml") and "struct" not in n.lower())
    names = []
    for m in re.finditer(r'<\w+:Series\s([^>]*)>(.*?)</\w+:Series>', xml, re.S):
        attrs, body = m[1], m[2]
        nm = (re.search(r'SERIES_NAME="([^"]+)"', attrs) or [None, ""])[1]
        names.append(nm)
        # M2, seasonally adjusted (the not seasonally adjusted series carry _N)
        if nm == "M2.M":  # M2, monthly, seasonally adjusted
            obs = re.findall(r'TIME_PERIOD="(\d{4}-\d{2})(?:-\d{2})?"\s+OBS_VALUE="([-\d.]+)"', body)
            obs += [(t, v) for v, t in re.findall(r'OBS_VALUE="([-\d.]+)"\s+TIME_PERIOD="(\d{4}-\d{2})', body)]
            if obs:
                print("M2 history from", nm, len(obs), file=sys.stderr)
                return sorted([t, float(v)] for t, v in obs)
    raise ValueError(f"M2 history: no SA M2 series among {[n for n in names if 'M2' in n][:10]}")


def m2(old):
    new = parse_h6(get("https://www.federalreserve.gov/releases/h6/current/default.htm"))
    if len(new) < 13:
        raise ValueError("M2: under 13 months")
    hist = {h[0]: h for h in (old or {}).get("hist", [])}
    if len(hist) < 36:  # once: five years from the data package
        try:
            hist.update({h[0]: h for h in m2_history() if h[0] >= f"{date.today().year - 5}-01"})
        except Exception as e:  # noqa: BLE001
            print(e, file=sys.stderr)
    hist.update({h[0]: h for h in new})  # the current table's months (revised) replace older readings
    hist = sorted(hist.values())[-60:]
    return {"month": new[-1][0], "hist": hist}


def main():
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    now = datetime.now(timezone.utc)
    try:
        checked = json.loads(CHECKED.read_text())
    except (OSError, ValueError):
        checked = {}
    KEYS = ("fed", "rrp", "m2", "money")
    out = {k: old[k] for k in KEYS if k in old}
    for k, f in (("fed", lambda: fed(old.get("fed"))), ("rrp", lambda: rrp(old.get("rrp"))), ("m2", lambda: m2(old.get("m2"))),
                 ("money", lambda: money(old.get("money")))):
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
    if all(old.get(k) == out.get(k) for k in KEYS):
        return
    out["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print({k: (out[k].get("week") or out[k].get("date") or out[k].get("month")) for k in ("fed", "rrp", "m2") if k in out},
          "spread", (out.get("money") or {}).get("spread", [])[-1:], "repo days", len((out.get("money") or {}).get("repo", [])))


if __name__ == "__main__":
    main()
