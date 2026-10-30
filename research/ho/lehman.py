"""Nasdaq 100 (^NDX) and QQQ, TECL daily data 2007-2012 for a look at the Lehman signals with a 3x path."""
import yfinance as yf, pandas as pd
from pathlib import Path
H = Path(__file__).resolve().parent
out = {}
for s in ["^NDX", "QQQ", "TECL", "^GSPC"]:
    df = yf.download(s, start="2007-06-01", end="2012-12-31", auto_adjust=True, progress=False)
    c = df["Close"]; l = df["Low"]
    if hasattr(c, "columns"): c, l = c.iloc[:, 0], l.iloc[:, 0]
    out[s + "_c"] = c; out[s + "_l"] = l
pd.DataFrame(out).to_csv(H / "lehman.csv")
