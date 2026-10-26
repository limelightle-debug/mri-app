"""Estimate the Cboe SKEW Index from Cboe's delayed SPX option quotes.

Cboe publishes SKEW once a day, at the close. This recomputes it from the option chain with
Cboe's published method (the same option selection as VIX; the skewness of the 30-day
risk-neutral distribution, SKEW = 100 - 10 * S), so it can be compared with the official close
and, if it tracks it, used during the session.

Writes data/skew_calc.json: {"at", "quoteTime", "skew", "official", "terms": [...]}.
"""
import json
import math
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from mkt_calendar import is_trading_day, options_close_minutes

NY = ZoneInfo("America/New_York")
OUT = Path(__file__).resolve().parent.parent / "data" / "skew_calc.json"
LOG = OUT.with_name("skew_log.csv")  # every estimate, to compare with the official closes
CHAIN = "https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json"
SKEW_Q = "https://cdn.cboe.com/api/global/delayed_quotes/quotes/_SKEW.json"
RATE = 0.04  # risk-free rate; its effect on SKEW is small
SYM = re.compile(r"^(SPXW?)(\d{6})([CP])(\d{8})$")
MIN_DAYS, MAX_DAYS = 23, 37
# a snapshot is sane when its SKEW is within SANE_SKEW points of the last close-time value (SKEW's largest daily move
# since 1990 is 24.8; broken snapshots were 55 off) and its VIX is at least SANE_VIX of the close-time value (VIX's
# lowest low against the previous close is 0.59, 2020-03-24; broken snapshots were 0.65 with SKEW far off)
SANE_SKEW, SANE_VIX = 30, .5
# between two sane snapshots within 3 hours, a jump of more than JUMP_SKEW points or JUMP_VIX in VIX waits for
# the next snapshot to confirm it (a lone broken snapshot once gave SKEW 122 between two 149s)
JUMP_SKEW, JUMP_VIX = 6, .15


def get(url):
    r = requests.get(url, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()


def parse_time(s, tz=NY):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[:19], fmt).replace(tzinfo=tz).astimezone(NY)
        except ValueError:
            pass
    return None


def chain():
    j = get(CHAIN)
    d = j.get("data", j)
    t = parse_time(str(j.get("timestamp") or ""), ZoneInfo("UTC")) or datetime.now(NY)
    terms = {}
    for o in d["options"]:
        m = SYM.match(o.get("option", ""))
        if not m:
            continue
        root, ymd, cp, k = m.groups()
        day = datetime.strptime(ymd, "%y%m%d")
        # monthly SPX options settle at the open, weekly SPXW at the close
        exp = day.replace(hour=9, minute=30, tzinfo=NY) if root == "SPX" else day.replace(hour=16, tzinfo=NY)
        bid, ask = o.get("bid") or 0, o.get("ask") or 0
        terms.setdefault((exp, root), {}).setdefault(int(k) / 1000, {})[cp] = (float(bid), float(ask))
    return t, terms


def term_moments(strikes, T):
    ks = sorted(strikes)
    mid = lambda q: (q[0] + q[1]) / 2
    both = [k for k in ks if "C" in strikes[k] and "P" in strikes[k] and strikes[k]["C"][1] > 0 and strikes[k]["P"][1] > 0]
    if not both:
        return None
    kf = min(both, key=lambda k: abs(mid(strikes[k]["C"]) - mid(strikes[k]["P"])))
    F = kf + math.exp(RATE * T) * (mid(strikes[kf]["C"]) - mid(strikes[kf]["P"]))
    below = [k for k in ks if k <= F]
    if not below:
        return None
    k0 = below[-1]
    # out-of-the-money options, stopping after two consecutive zero bids (as for VIX)
    sel = {}
    zeros = 0
    for k in reversed([k for k in ks if k < k0]):
        q = strikes[k].get("P")
        if not q or q[0] <= 0:
            zeros += 1
            if zeros >= 2:
                break
            continue
        zeros = 0
        sel[k] = mid(q)
    zeros = 0
    for k in [k for k in ks if k > k0]:
        q = strikes[k].get("C")
        if not q or q[0] <= 0:
            zeros += 1
            if zeros >= 2:
                break
            continue
        zeros = 0
        sel[k] = mid(q)
    q0 = [mid(strikes[k0][c]) for c in "PC" if c in strikes[k0]]
    sel[k0] = sum(q0) / len(q0)
    sk = sorted(sel)
    e = math.exp(RATE * T)
    p0 = p1 = p2 = p3 = 0.0
    for i, k in enumerate(sk):
        dk = (sk[min(i + 1, len(sk) - 1)] - sk[max(i - 1, 0)]) / (1 if i in (0, len(sk) - 1) else 2)
        q, lk = sel[k], math.log(k / F)
        p0 += q * dk / k ** 2
        p1 += -1 / k ** 2 * q * dk
        p2 += 2 / k ** 2 * (1 - lk) * q * dk
        p3 += 3 / k ** 2 * (2 * lk - lk ** 2) * q * dk
    l0 = math.log(k0 / F)
    e1 = -(1 + math.log(F / k0) - F / k0)
    e2 = 2 * l0 * (F / k0 - 1) + 0.5 * l0 ** 2
    e3 = 3 * l0 ** 2 * (l0 / 3 - 1 + F / k0)
    P1, P2, P3 = e * p1 + e1, e * p2 + e2, e * p3 + e3
    var = P2 - P1 ** 2
    if var <= 0:
        return None
    S = (P3 - 3 * P1 * P2 + 2 * P1 ** 3) / var ** 1.5
    puts_bid = sum(1 for k in ks if k < k0 and strikes[k].get("P", (0, 0))[0] > 0)
    calls_bid = sum(1 for k in ks if k > k0 and strikes[k].get("C", (0, 0))[0] > 0)
    # the term's variance as in Cboe's VIX method (same options)
    var_vix = 2 / T * e * p0 - (F / k0 - 1) ** 2 / T
    return {"F": round(F, 2), "K0": k0, "n": len(sk), "strikes": len(ks), "putsWithBid": puts_bid,
            "callsWithBid": calls_bid, "lowK": sk[0], "highK": sk[-1], "S": S, "varVix": var_vix}


def judge(prev, snap, anchors, anchors_v):
    """Whether to take a new snapshot ({quoteTime, skew, vix}) over the last result `prev`; returns (take, rejected),
    `rejected` the snapshot when it is not taken (kept in the output, so the next run can confirm a real jump).

    Insane (see SANE_*): not taken. Sane after an insane or missing last result: taken (a bad result never locks in).
    Sane after a sane last result: taken unless it jumps (JUMP_*) within 3 hours; a jump is taken once the next
    snapshot agrees with it (a real move stays, a broken snapshot does not)."""
    def sane(sk, vx):
        if sk is None:
            return False
        if not anchors:
            return True
        ka = max(anchors)
        av = anchors_v.get(ka)
        return abs(sk - anchors[ka]) <= SANE_SKEW and not (vx and av and vx / av < SANE_VIX)
    def near(a, b):
        return abs(a["skew"] - b["skew"]) <= JUMP_SKEW and not (a.get("vix") and b.get("vix") and abs(a["vix"] / b["vix"] - 1) > JUMP_VIX)
    rec = {"quoteTime": snap["quoteTime"], "skew": round(snap["skew"], 2), "vix": snap["vix"] and round(snap["vix"], 4)}
    if not sane(snap["skew"], snap["vix"]):
        return (False, rec) if prev.get("skew") is not None and prev.get("quoteTime") else (True, None)
    if prev.get("skew") is None or not prev.get("quoteTime") or not sane(prev["skew"], prev.get("vix")):
        return True, None
    t, pt = datetime.fromisoformat(snap["quoteTime"]), datetime.fromisoformat(prev["quoteTime"])
    if abs((t - pt).total_seconds()) >= 3 * 3600 or near(snap, prev):
        return True, None
    last_rej = prev.get("rejected")
    if last_rej and last_rej.get("skew") is not None and near(snap, last_rej):
        return True, None  # the jump held for a second snapshot: a real move
    return False, rec


def main():
    t, terms = chain()
    cand = []
    for (exp, root), strikes in terms.items():
        days = (exp - t).total_seconds() / 86400
        if MIN_DAYS <= days <= MAX_DAYS:
            cand.append((exp, root, strikes))
    cand.sort(key=lambda c: c[0])
    # near term: the latest expiry within 30 days; next term: the earliest after 30 days
    target = t + timedelta(days=30)
    near = [c for c in cand if c[0] <= target]
    nxt = [c for c in cand if c[0] > target]
    if not near or not nxt:
        raise RuntimeError(f"no expiries around 30 days (found {[(c[0].isoformat(), c[1]) for c in cand]})")
    out = []
    for exp, root, strikes in (near[-1], nxt[0]):
        T = (exp - t).total_seconds() / (365 * 86400)
        m = term_moments(strikes, T)
        if not m:
            raise RuntimeError(f"cannot compute {root} {exp}")
        out.append({"exp": exp.isoformat(), "root": root, "T": T, **m})
    T1, T2, T30 = out[0]["T"], out[1]["T"], 30 / 365
    w = (T2 - T30) / (T2 - T1)
    S = w * out[0]["S"] + (1 - w) * out[1]["S"]
    skew = 100 - 10 * S
    # VIX recomputed the same way (30-day interpolation of the two terms' variance); used overnight,
    # when Cboe's own quote does not show the overnight session, as a ratio to the value at the close
    v30 = (T1 * out[0]["varVix"] * (T2 - T30) / (T2 - T1) + T2 * out[1]["varVix"] * (T30 - T1) / (T2 - T1)) / T30
    vixc = 100 * math.sqrt(v30) if v30 > 0 else None
    try:
        q = get(SKEW_Q)["data"]
        official = {"value": q.get("current_price") or q.get("close"), "time": q.get("last_trade_time")}
    except Exception as e:  # noqa: BLE001
        official = {"error": str(e)}
    # the estimate from the closing quotes (after 16:15 and before the overnight session) is that
    # day's anchor: during the next session, SKEW = official close + (estimate - anchor)
    # the same for the S&P 500 forward implied by the options (put-call parity), per expiry: the
    # index does not trade overnight, but its options do
    forwards = {o["exp"]: o["F"] for o in out}
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prev = {}
    anchors, anchors_f, anchors_v = prev.get("anchors", {}), prev.get("anchorsF", {}), prev.get("anchorsV", {})
    take, rejected = judge(prev, {"quoteTime": t.isoformat(timespec="seconds"), "skew": skew, "vix": vixc}, anchors, anchors_v)
    if not take:
        # keep the last result whole (its time, values, forwards and terms)
        skew, vixc, forwards, out = prev["skew"], prev.get("vix"), prev.get("forwards", forwards), prev.get("terms", out)
        t = datetime.fromisoformat(prev["quoteTime"]).astimezone(NY)
    mins = t.hour * 60 + t.minute
    if is_trading_day(t.date()) and options_close_minutes(t.date()) <= mins < 20 * 60:
        anchors[t.strftime("%Y%m%d")] = round(skew, 3)
        anchors_f[t.strftime("%Y%m%d")] = forwards
        if vixc:
            anchors_v[t.strftime("%Y%m%d")] = round(vixc, 4)
    anchors = dict(sorted(anchors.items())[-30:])
    anchors_f = dict(sorted(anchors_f.items())[-30:])
    anchors_v = dict(sorted(anchors_v.items())[-30:])
    res = {"at": datetime.now(NY).isoformat(timespec="seconds"), "quoteTime": t.isoformat(timespec="seconds"),
           "skew": round(skew, 2), "official": official, "weightNear": round(w, 4),
           "terms": [{k: (round(v, 6) if isinstance(v, float) else v) for k, v in o.items()} for o in out] if take else out,
           "vix": None if vixc is None else round(vixc, 4),
           "forwards": forwards, "anchors": anchors, "anchorsF": anchors_f, "anchorsV": anchors_v,
           **({"rejected": rejected} if rejected else {})}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    new = not LOG.exists()
    with LOG.open("a", encoding="utf-8") as f:
        if new:
            f.write("quote_time,estimate,official,official_time\n")
        f.write(f"{res['quoteTime']},{res['skew']},{official.get('value', '')},{official.get('time', '')}\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
