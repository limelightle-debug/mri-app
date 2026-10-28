"""One-off probe (3): futures prices for gold, WTI and copper."""
import json, requests
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NH = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
out = {}
def get(name, url, headers, n=600):
    try:
        r = requests.get(url, headers=headers, timeout=30)
        out[name] = f"{r.status_code} " + r.text[:n]
    except Exception as e:
        out[name] = "ERR " + str(e)[:200]
for c in ["futures", "commodity", "Commodities", "FUTURES"]:
    get(f"nasdaq:GC:{c}", f"https://api.nasdaq.com/api/quote/GC%3ACMX/info?assetclass={c}", NH, 500)
get("nasdaq:search", "https://api.nasdaq.com/api/autocomplete/slookup/10?search=gold%20futures", NH, 800)
get("cme:gold", "https://www.cmegroup.com/CmeWS/mvc/Quotes/Future/437/G", {"User-Agent": UA, "Accept": "application/json"}, 500)
get("cme:wti", "https://www.cmegroup.com/CmeWS/mvc/Quotes/Future/425/G", {"User-Agent": UA, "Accept": "application/json"}, 500)
get("metals.live", "https://api.metals.live/v1/spot", {"User-Agent": UA}, 400)
get("goldprice", "https://data-asg.goldprice.org/dbXRates/USD", {"User-Agent": UA, "Referer": "https://goldprice.org/"}, 400)
get("cnbc:gold", "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=%40GC.1%7C%40CL.1%7C%40HG.1%7CUS10Y%7CJPY%3D&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1", {"User-Agent": UA}, 1500)
get("wsj", "https://www.wsj.com/market-data/commodities", {"User-Agent": UA}, 200)
open("data/probe_cmdty.json", "w").write(json.dumps(out, indent=1, ensure_ascii=False))
