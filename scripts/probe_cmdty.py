"""One-off probe: which sources answer for gold, WTI, copper and bitcoin from GitHub Actions."""
import json, time, requests
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NH = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
out = {}
def tryit(name, url, headers, pick):
    try:
        r = requests.get(url, headers=headers, timeout=30)
        out[name] = {"status": r.status_code, "val": pick(r.json()) if r.ok else r.text[:200]}
    except Exception as e:
        out[name] = {"err": str(e)[:200]}
def yh(j):
    m = j["chart"]["result"][0]["meta"]
    return {k: m.get(k) for k in ("symbol", "regularMarketPrice", "chartPreviousClose", "previousClose", "regularMarketTime", "currency")}
for s in ["GC=F", "CL=F", "HG=F", "BTC-USD", "^TNX", "^IRX", "2YY=F", "JPY=X", "DX-Y.NYB", "^FVX", "^TYX"]:
    for host in ["query1", "query2"]:
        tryit(f"yahoo:{host}:{s}", f"https://{host}.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(s)}?range=5d&interval=1d", {"User-Agent": UA}, yh)
def nq(j):
    p = (j.get("data") or {}).get("primaryData") or {}
    return {k: p.get(k) for k in ("lastSalePrice", "netChange", "percentageChange", "lastTradeTimestamp")}
for s, c in [("GC:CMX", "commodities"), ("CL:NMX", "commodities"), ("HG:CMX", "commodities"), ("BTC", "crypto")]:
    tryit(f"nasdaq:{s}", f"https://api.nasdaq.com/api/quote/{requests.utils.quote(s)}/info?assetclass={c}", NH, nq)
tryit("coinbase:BTC", "https://api.coinbase.com/v2/prices/BTC-USD/spot", {"User-Agent": UA}, lambda j: j)
tryit("fred:DGS10", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10", {"User-Agent": UA}, lambda j: j)
open("data/probe_cmdty.json", "w").write(json.dumps(out, indent=1, ensure_ascii=False))
