"""The VIX app's event notes (data/vix_notes.json): for each VIX event, the day-by-day table the institute keeps in
its workbook and posted during the 2025 event. From 9 trading days before the start to the event's end:
the VIX daily high, its 5-day and 10-day linearly weighted moving averages (weights 1..n, the latest heaviest),
the S&P 500's low and its change from the first row's low, and the notes of 『VIXの声を聴け』 chapter 10:
  start          the first day whose high passes +2 sigma (as of the month before the start)
  5d decline     the first day the 5-day LWMA falls (the fear's momentum is fading)
  buy signal     then the first day the 10-day LWMA falls, or the 5-day crosses below the 10-day
  wave end       after the signal, the 5th day in a row whose high stays below +2 sigma (counted 1-5)
  next wave      a high above +2 sigma again after a wave ended: the same rules again
  event end      the 10th day in a row whose high stays below +1 sigma (counted 1-10), as in vix.json
Thresholds: +1/+2/+3 sigma of the month before the start (vix.json months: 10^(mean + k sd) of log monthly highs).
A note is kept as it was once its event has ended (later data revisions don't rewrite it); `--rebuild` redoes all.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "vix_notes.json"
# the names in 『VIXの声を聴け』 (figure 1-1), and English ones in the workbook's manner
NAMES = {
    "199710": ["アジア通貨危機", "The Asian Financial Crisis"],
    "199809": ["LTCMショック", "The LTCM Shock"],
    "200109": ["同時多発テロ", "The September 11 Attacks"],
    "200207": ["ITバブル崩壊", "The Dot-com Bust"],
    "200809": ["リーマンショック", "The Lehman Shock"],
    "201005": ["欧州ソブリン危機", "The European Sovereign Debt Crisis"],
    "201108": ["米国債格下げショック", "The US Downgrade Shock"],
    "201508": ["チャイナショック", "The China Shock"],
    "201802": ["ボラゲドン", "Volmageddon"],
    "202002": ["コロナショック", "The COVID-19 Shock"],
    "202408": ["円キャリー崩壊", "The Yen Carry Unwind"],
    "202504": ["世界関税ショック", "The World Tariff Shock"],
}
ORD = lambda n: f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def add_months(m, k):
    y, mo = divmod(m // 100 * 12 + m % 100 - 1 + k, 12)
    return y * 100 + mo + 1


def lwma(v, i, n):
    if i - n + 1 < 0 or any(x is None for x in v[i - n + 1:i + 1]):
        return None
    w = range(1, n + 1)
    return sum(a * b for a, b in zip(w, v[i - n + 1:i + 1])) / sum(w)


def note(ym, ev, months, dl, hi, spx):
    by_m = {r[0]: r for r in months}
    pr = by_m.get(add_months(ym, -1), by_m[ym])
    t1, t2, t3 = (10 ** (pr[4] + k * pr[5]) for k in (1, 2, 3))
    s, e = ev["day"], ev.get("end")
    i_s = dl.index(s)
    i0, i1 = max(0, i_s - 9), (dl.index(e) if e in dl else len(dl) - 1)
    days = dl[i0:i1 + 1]
    H = [hi[d] for d in dl]
    L5 = [lwma(H, i, 5) if i - i0 >= 4 else None for i in range(len(dl))]
    L10 = [lwma(H, i, 10) if i - i0 >= 9 else None for i in range(len(dl))]
    rows = []
    for i in range(i0, i1 + 1):
        d = dl[i]
        lo = spx.get(d)
        rows.append({"d": d, "h": H[i], "l5": L5[i], "l10": L10[i], "lo": lo, "n": None, "k": "", "m": [], "hl": []})
    base = next((r["lo"] for r in rows if r["lo"] is not None), None)
    for r in rows:
        r["pct"] = None if r["lo"] is None or base is None else r["lo"] / base - 1
    R = lambda i: rows[i - i0]
    # waves
    wave, i, state, cnt = 1, i_s, "rise", 0
    R(i_s)["m"].append(["start", wave])
    while i < i1:
        i += 1
        r, h = R(i), H[i]
        if state == "rise":
            if L5[i] is not None and L5[i - 1] is not None and L5[i] < L5[i - 1]:
                r["m"].append(["d5", wave]); r["hl"].append("l5"); state = "fade"
                if L10[i] is not None and L10[i - 1] is not None and (L10[i] < L10[i - 1] or L5[i] < L10[i]):
                    r["m"].append(["buy", wave, "d10" if L10[i] < L10[i - 1] else "x"]); r["hl"].append("l10"); state, cnt = "wait", 0
        elif state == "fade":
            if L10[i] is not None and L10[i - 1] is not None and (L10[i] < L10[i - 1] or L5[i] < L10[i]):
                r["m"].append(["buy", wave, "d10" if L10[i] < L10[i - 1] else "x"]); r["hl"].append("l10"); state, cnt = "wait", 0
        elif state == "wait":
            cnt = cnt + 1 if h < t2 else 0
            if cnt:
                r["n"], r["k"] = cnt, "w"
            if cnt == 5:
                r["m"].append(["wend", wave]); state = "after"
        elif state == "after" and h > t2:
            wave += 1
            r["m"].append(["start", wave]); state = "rise"
    # the event end count: the run of days below +1 sigma that ends the event (or the run so far)
    j, run = i1, []
    while j > i_s and H[j] < t1:
        run.append(j); j -= 1
    run = run[::-1]
    if e or (run and any(m[0] == "wend" for rr in rows for m in rr["m"])):
        for k, j in enumerate(run[:10]):
            r = R(j)
            r.setdefault("e", k + 1)
    if e:
        R(i1)["m"].append(["end"])
    lows = [(r["lo"], k) for k, r in enumerate(rows) if r["lo"] is not None]
    bottom = rows[min(lows)[1]]["d"] if lows else None
    rnd = lambda v, n=2: None if v is None else round(v, n)
    out_rows = []
    for r in rows:
        out_rows.append([r["d"], rnd(r["h"]), rnd(r["l5"]), rnd(r["l10"]), rnd(r["lo"]), rnd(r["pct"], 4),
                         r["n"], r.get("e"), r["m"], r["hl"]])
    nm = NAMES.get(str(ym), [f"VIXイベント {ym // 100}", f"VIX event {ym // 100}"])
    return {"ym": ym, "name": nm[0], "en": nm[1], "year": s // 10000, "start": s, "end": e, "active": e is None,
            "sig": [round(t1, 2), round(t2, 2), round(t3, 2)], "sigFrom": add_months(ym, -1), "bottom": bottom,
            "waves": wave, "cols": ["date", "vixHigh", "lwma5", "lwma10", "spxLow", "spxChg", "waveCount", "endCount",
                                    "marks", "highlight"], "rows": out_rows}


def main(rebuild=False):
    vix = json.loads((DATA / "vix.json").read_text())
    highs = json.loads((DATA / "vix_daily.json").read_text())["high"]
    hi = {d: h for d, h in highs}
    dl = sorted(hi)
    sp = DATA / "spx_daily.json"
    spx = {r[0]: r[1] for r in json.loads(sp.read_text())["hist"]} if sp.exists() else {}
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    kept = {} if rebuild else {str(n["ym"]): n for n in old.get("notes", []) if not n.get("active") and n.get("frozenAt")}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    notes = []
    for ym in vix["events"]:
        key = str(ym)
        if key in kept:
            notes.append(kept[key]); continue
        ev = vix["eventInfo"][key]
        if ev["day"] not in hi:
            continue
        n = note(ym, ev, vix["months"], dl, hi, spx)
        if not n["active"] and spx and all(r[4] is not None for r in n["rows"]):
            n["frozenAt"] = now  # an ended event's note with its full table: kept as it is from now on
        notes.append(n)
    out = {"updatedAt": now, "notes": notes}
    if {k: v for k, v in old.items() if k != "updatedAt"} == {k: v for k, v in out.items() if k != "updatedAt"}:
        return
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(len(notes), "notes;", sum(1 for n in notes if n["active"]), "active")


if __name__ == "__main__":
    main(rebuild="--rebuild" in sys.argv)
