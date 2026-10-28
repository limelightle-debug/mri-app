"""One-off probe (2): raw Nasdaq commodity answers, stooq, Cboe ETFs."""
import json, requests
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NH = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
out = {}
def get(name, url, headers, n=700):
    try:
        r = requests.get(url, headers=headers, timeout=30)
        out[name] = f"{r.status_code} " + r.text[:n]
    except Exception as e:
        out[name] = "ERR " + str(e)[:200]
for s in ["GC:CMX", "CL:NMX", "HG:CMX", "SI:CMX"]:
    get(f"nasdaq-info:{s}", f"https://api.nasdaq.com/api/quote/{s}/info?assetclass=commodities", NH, 1200)
get("nasdaq-summary:GC", "https://api.nasdaq.com/api/quote/GC:CMX/summary?assetclass=commodities", NH)
for s in ["gc.f", "cl.f", "hg.f", "btcusd", "10usy.b", "2usy.b", "usdjpy", "dx.f"]:
    get(f"stooq:{s}", f"https://stooq.com/q/l/?s={s}&f=sd2t2ohlcp&h&e=csv", {"User-Agent": UA}, 300)
for s in ["GLD", "USO", "CPER", "IBIT", "_TNX", "_IRX", "_FVX", "_TYX"]:
    get(f"cboe:{s}", f"https://cdn.cboe.com/api/global/delayed_quotes/quotes/{s}.json", {"User-Agent": UA}, 400)
open("data/probe_cmdty.json", "w").write(json.dumps(out, indent=1, ensure_ascii=False))
