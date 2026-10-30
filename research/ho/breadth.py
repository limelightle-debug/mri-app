"""Breadth of the S&P 500's members, day by day, for a test of the Hindenburg Omen's idea (many new highs and many
new lows at once). Point-in-time membership (components.csv, fja05680/sp500, from 1996); prices from Yahoo
(yfinance, adjusted). Yahoo keeps only symbols that still trade, so members that were delisted are missing: the
coverage is written out beside the counts.

Out: breadth.csv, one row a day:
  date, members, covered, nh, nl, adv, dec, nhc, nlc, cur_cov, cur_nh, cur_nl, spx
  nh / nl: covered members whose high / low that day is the highest / lowest of the last 252 sessions (intraday)
  nhc / nlc: the same on closes; adv / dec: closes up / down on the day
  cur_*: the same counts for today's members only (the survivor universe), for comparison
coverage.csv: each symbol, its first and last day in the index, and the first day Yahoo has.
"""
import csv
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

HERE = Path(__file__).resolve().parent
rows = list(csv.DictReader(open(HERE / "components.csv")))
mem = [(pd.Timestamp(r["date"]), set(t.strip() for t in r["tickers"].split(",") if t.strip())) for r in rows]
syms = sorted(set().union(*[m for _, m in mem]))
current = mem[-1][1]
print(len(syms), "symbols;", len(current), "current", file=sys.stderr)

ysym = {s: s.replace(".", "-") for s in syms}
H, L, C = {}, {}, {}
for i in range(0, len(syms), 80):
    chunk = syms[i:i + 80]
    for attempt in range(3):
        try:
            df = yf.download([ysym[s] for s in chunk], start="1995-01-01", auto_adjust=True, progress=False,
                             group_by="ticker", threads=True)
            break
        except Exception as e:  # noqa: BLE001
            print("retry", i, e, file=sys.stderr)
            time.sleep(10)
    else:
        continue
    for s in chunk:
        y = ysym[s]
        try:
            d = df[y] if len(chunk) > 1 else df
        except KeyError:
            continue
        d = d.dropna(subset=["Close"])
        if len(d) < 260:
            continue
        H[s], L[s], C[s] = d["High"], d["Low"], d["Close"]
    print(i, len(C), file=sys.stderr)

spx = yf.download("^GSPC", start="1995-01-01", auto_adjust=True, progress=False)["Close"]
if isinstance(spx, pd.DataFrame):
    spx = spx.iloc[:, 0]
idx = spx.index
Hm = pd.DataFrame(H).reindex(idx)
Lm = pd.DataFrame(L).reindex(idx)
Cm = pd.DataFrame(C).reindex(idx)
cols = list(Cm.columns)
W = 252
# a high (low) that is the highest (lowest) of the last 252 sessions, needing a full year of data
hh = Hm.rolling(W, min_periods=W).max()
ll = Lm.rolling(W, min_periods=W).min()
ch = Cm.rolling(W, min_periods=W).max()
cl = Cm.rolling(W, min_periods=W).min()
okw = Cm.notna().rolling(W, min_periods=W).sum() >= W - 5
nh = (Hm >= hh) & okw
nl = (Lm <= ll) & okw
nhc = (Cm >= ch) & okw
nlc = (Cm <= cl) & okw
r1 = Cm.diff()
adv, dec = r1 > 0, r1 < 0

mdates = [m[0] for m in mem]
out = []
cur_mask = np.array([c in current for c in cols])
for k, t in enumerate(idx):
    j = np.searchsorted(mdates, t, side="right") - 1
    if j < 0:
        continue
    members = mem[j][1]
    mask = np.array([c in members for c in cols])
    cov = mask & okw.iloc[k].values & Cm.iloc[k].notna().values
    cc = cur_mask & okw.iloc[k].values & Cm.iloc[k].notna().values
    out.append([t.strftime("%Y-%m-%d"), len(members), int(cov.sum()),
                int((nh.iloc[k].values & cov).sum()), int((nl.iloc[k].values & cov).sum()),
                int((adv.iloc[k].values & cov).sum()), int((dec.iloc[k].values & cov).sum()),
                int((nhc.iloc[k].values & cov).sum()), int((nlc.iloc[k].values & cov).sum()),
                int(cc.sum()), int((nh.iloc[k].values & cc).sum()), int((nl.iloc[k].values & cc).sum()),
                round(float(spx.iloc[k]), 2)])
with open(HERE / "breadth.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date", "members", "covered", "nh", "nl", "adv", "dec", "nhc", "nlc", "cur_cov", "cur_nh", "cur_nl",
                "spx"])
    w.writerows(out)
with open(HERE / "coverage.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["symbol", "in_index_first", "in_index_last", "yahoo_first"])
    for s in syms:
        days = [d for d, m in mem if s in m]
        w.writerow([s, days[0].strftime("%Y-%m-%d"), days[-1].strftime("%Y-%m-%d"),
                    C[s].index[0].strftime("%Y-%m-%d") if s in C else ""])
print("rows", len(out), "symbols with data", len(C), file=sys.stderr)
