"""Debug: save Cboe's raw delayed quotes (and the option chain's header) to the given folder."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0"}
for s in ("VIX", "SKEW", "SPX"):
    r = requests.get(f"https://cdn.cboe.com/api/global/delayed_quotes/quotes/_{s}.json", headers=H, timeout=60)
    (out / f"{s}.json").write_text(json.dumps(r.json(), indent=1) if r.ok else f"HTTP {r.status_code}")
r = requests.get("https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json", headers=H, timeout=120)
j = r.json()
d = j.get("data", {})
o = d.get("options", [])
(out / "chain_head.json").write_text(json.dumps({"top": {k: v for k, v in j.items() if k != "data"},
                                                 "data": {k: v for k, v in d.items() if k != "options"},
                                                 "n": len(o), "sample": o[:3]}, indent=1))
(out / "fetched_at.txt").write_text(datetime.now(timezone.utc).isoformat())
