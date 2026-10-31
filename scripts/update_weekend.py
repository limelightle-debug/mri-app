"""Bitcoin over the weekend, for the paper's Sunday edition: data/weekend.json.

Bitcoin trades through the weekend while the other markets are shut. Each run adds CNBC's quote (BTC.CM=) to a
list that starts again each weekend (from Friday 16:00 US Eastern). The app compares the latest with Friday's close
in weekly.json.
{"hist": [[ISO time UTC, price], ...], "updatedAt"}
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "weekend.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
URL = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=BTC.CM%3D"
       "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")
NY = ZoneInfo("America/New_York")


def main():
    r = requests.get(URL, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    q = r.json()["FormattedQuoteResult"]["FormattedQuote"][0]
    price = float(str(q["last"]).replace(",", ""))
    now = datetime.now(timezone.utc)
    # this weekend starts at the last Friday 16:00 ET
    ny = now.astimezone(NY)
    fri = (ny - timedelta(days=(ny.weekday() - 4) % 7)).replace(hour=16, minute=0, second=0, microsecond=0)
    if fri > ny:
        fri -= timedelta(days=7)
    start = fri.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    hist = [h for h in old.get("hist", []) if h[0] >= start]
    hist.append([now.strftime("%Y-%m-%dT%H:%M:%SZ"), round(price, 2)])
    out = {"from": start, "hist": hist, "updatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(hist[-1])


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        sys.exit(f"weekend: {type(e).__name__}: {e}")
