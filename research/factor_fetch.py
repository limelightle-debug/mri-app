"""One-off: fetch SEC XBRL frames and monthly prices for an accruals backtest (writes to the given folder)."""
import gzip, json, sys, time, os
import requests

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "fear-index-research admin@fear-index.invalid"}
DUR = ["NetIncomeLoss", "NetCashProvidedByUsedInOperatingActivities", "Revenues",
       "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]
INST = ["Assets", "AccountsReceivableNetCurrent"]
frames = {}
for c in DUR + INST:
    for y in range(2008, 2026):
        per = f"CY{y}Q4I" if c in INST else f"CY{y}"
        url = f"https://data.sec.gov/api/xbrl/frames/us-gaap/{c}/USD/{per}.json"
        for t in range(3):
            r = requests.get(url, headers=H, timeout=60)
            if r.status_code == 200:
                frames[f"{c}|{per}"] = [[d["cik"], d["val"], d.get("end"), d.get("accn")] for d in r.json()["data"]]
                break
            if r.status_code == 404:
                break
            time.sleep(2)
        time.sleep(0.15)
        print(c, per, len(frames.get(f"{c}|{per}", [])), flush=True)
json.dump(frames, gzip.open(f"{OUT}/frames.json.gz", "wt"))

tick = requests.get("https://www.sec.gov/files/company_tickers.json", headers=H, timeout=60).json()
cik2t = {}
for v in tick.values():
    cik2t.setdefault(int(v["cik_str"]), v["ticker"])
json.dump(cik2t, open(f"{OUT}/cik2ticker.json", "w"))

big = set()
for k, rows in frames.items():
    if k.startswith("Assets|"):
        big |= {r[0] for r in rows if r[1] and r[1] >= 1e9}
tickers = sorted({cik2t[c] for c in big if c in cik2t})
print("tickers", len(tickers), flush=True)

import yfinance as yf
import pandas as pd
parts = []
for i in range(0, len(tickers), 150):
    chunk = [t.replace(".", "-") for t in tickers[i:i + 150]]
    for t in range(3):
        try:
            df = yf.download(chunk, start="2009-01-01", interval="1mo", auto_adjust=True, progress=False, threads=True)["Close"]
            parts.append(df)
            break
        except Exception as e:
            print("retry", i, e, flush=True)
            time.sleep(10)
    print("prices", i, flush=True)
    time.sleep(2)
px = pd.concat(parts, axis=1)
px.to_csv(f"{OUT}/prices_monthly.csv.gz")
print("done", px.shape)
