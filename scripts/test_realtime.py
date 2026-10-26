"""Offline checks of the realtime decisions at session boundaries: python scripts/test_realtime.py

Replays the snapshot decision (skew_calc.judge) over sequences seen or feared, and the session day and anchor window
over weekends, holidays and early closes."""
import sys
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkt_calendar import is_trading_day, options_close_minutes  # noqa: E402
from skew_calc import judge  # noqa: E402
from update_mri import session_day  # noqa: E402

NY = ZoneInfo("America/New_York")
ANCH, ANCH_V = {"20261023": 149.74}, {"20261023": 19.37}
fails = 0


def run(name, snaps, start, expect):
    """Feed snapshots (time, skew, vix) one by one; `expect` is the list of skews the output holds after each."""
    global fails
    prev, got = dict(start), []
    for tm, sk, vx in snaps:
        take, rej = judge(prev, {"quoteTime": tm, "skew": sk, "vix": vx}, ANCH, ANCH_V)
        if take:
            prev = {"quoteTime": tm, "skew": sk, "vix": vx}
        else:
            prev = {**prev, "rejected": rej}
        got.append(prev["skew"])
    ok = got == expect
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, got if not ok else "")


fri = {"quoteTime": "2026-10-23T17:28:00-04:00", "skew": 149.74, "vix": 19.37}
# the Monday-morning case: broken snapshots from Sunday night, then good ones from 5:49
run("broken weekend snapshots, then good", [
    ("2026-10-25T20:00:00-04:00", 95.0, 12.68), ("2026-10-26T03:13:00-04:00", 94.4, 12.63),
    ("2026-10-26T05:49:00-04:00", 148.91, 19.34), ("2026-10-26T05:52:00-04:00", 148.95, 19.34)],
    fri, [149.74, 149.74, 148.91, 148.95])
# a broken result already in place (as this morning): the first good snapshot must replace it
run("bad result in place, good snapshot replaces it", [("2026-10-26T05:49:00-04:00", 148.91, 19.34)],
    {"quoteTime": "2026-10-26T03:13:00-04:00", "skew": 94.4, "vix": 12.63}, [148.91])
# a lone broken snapshot within the session (once SKEW 122 between two 149s)
run("lone spike dropped", [("2026-10-22T11:00:00-04:00", 149.5, 19.2), ("2026-10-22T11:05:00-04:00", 136.0, 19.1),
    ("2026-10-22T11:10:00-04:00", 149.3, 19.2)], {"quoteTime": "2026-10-22T10:55:00-04:00", "skew": 149.6, "vix": 19.2},
    [149.5, 149.5, 149.3])
# a real crash: VIX up 40% and SKEW down 10 in minutes, and it stays: taken on the second snapshot
run("real jump confirmed by the next snapshot", [("2026-10-27T09:40:00-04:00", 139.5, 27.0),
    ("2026-10-27T09:45:00-04:00", 139.0, 27.5), ("2026-10-27T09:50:00-04:00", 138.0, 28.5)],
    {"quoteTime": "2026-10-27T09:35:00-04:00", "skew": 149.5, "vix": 19.3}, [149.5, 139.0, 138.0])
# a VIX collapse like 2025-04-09 (close 0.64 of the day before) must stay sane
run("VIX falling 36% stays sane", [("2026-10-27T14:00:00-04:00", 147.0, 12.5), ("2026-10-27T14:05:00-04:00", 147.2, 12.4)],
    {"quoteTime": "2026-10-27T13:55:00-04:00", "skew": 147.0, "vix": 12.6}, [147.0, 147.2])
# after three hours a big change is simply taken (a slow move through the night)
run("big change after 3 hours taken", [("2026-10-27T03:30:00-04:00", 141.0, 23.0)],
    {"quoteTime": "2026-10-26T23:00:00-04:00", "skew": 149.0, "vix": 19.4}, [141.0])

# session days
cases = [
    ("Fri 21:00 -> Mon", datetime(2026, 10, 23, 21, 0, tzinfo=NY), 20261026),
    ("Sun 21:00 -> Mon", datetime(2026, 10, 25, 21, 0, tzinfo=NY), 20261026),
    ("Wed before Thanksgiving 21:00 -> Fri", datetime(2026, 11, 25, 21, 0, tzinfo=NY), 20261127),
    ("Thanksgiving noon -> Fri", datetime(2026, 11, 26, 12, 0, tzinfo=NY), 20261127),
    ("Good Friday 2026 10:00 -> Mon", datetime(2026, 4, 3, 10, 0, tzinfo=NY), 20260406),
    ("ordinary Tue 10:00 -> Tue", datetime(2026, 10, 27, 10, 0, tzinfo=NY), 20261027),
]
for name, t, want in cases:
    got = session_day(t)
    fails += got != want
    print(("ok  " if got == want else "FAIL"), name, "" if got == want else got)
# anchors on early-close days start at 13:15
for name, d, want in (("early close 2026-11-27", date(2026, 11, 27), 13 * 60 + 15), ("ordinary day", date(2026, 10, 27), 16 * 60 + 15)):
    got = options_close_minutes(d)
    fails += got != want
    print(("ok  " if got == want else "FAIL"), name, "" if got == want else got)
for name, d, want in (("Thanksgiving closed", date(2026, 11, 26), False), ("Saturday closed", date(2026, 10, 24), False),
                      ("Monday open", date(2026, 10, 26), True)):
    got = is_trading_day(d)
    fails += got != want
    print(("ok  " if got == want else "FAIL"), name, "" if got == want else got)
# holidays from the rules match NYSE's published lists
from mkt_calendar import holidays  # noqa: E402
nyse = {2025: {date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17), date(2025, 4, 18), date(2025, 5, 26), date(2025, 6, 19),
               date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27), date(2025, 12, 25)},
        2027: {date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 31), date(2027, 6, 18),
               date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25), date(2027, 12, 24)},
        2028: {date(2028, 1, 17), date(2028, 2, 21), date(2028, 4, 14), date(2028, 5, 29), date(2028, 6, 19), date(2028, 7, 4),
               date(2028, 9, 4), date(2028, 11, 23), date(2028, 12, 25)}}
for y, want in nyse.items():
    got = set(holidays(y))
    fails += got != want
    print(("ok  " if got == want else "FAIL"), f"NYSE holidays {y}", "" if got == want else sorted(got ^ want))
# when the updates run (weekends, holidays and Cboe's holiday trading hours)
from mkt_calendar import session_mode  # noqa: E402
for name, t, want in [
        ("Sun 21:00", datetime(2026, 10, 25, 21, 0), "closed"), ("Mon 01:00 after a weekend", datetime(2026, 10, 26, 1, 0), "closed"),
        ("Mon 03:30", datetime(2026, 10, 26, 3, 30), "pre"), ("Mon 10:00", datetime(2026, 10, 26, 10, 0), "open"),
        ("Mon 18:00", datetime(2026, 10, 26, 18, 0), "closed"), ("Mon 21:00", datetime(2026, 10, 26, 21, 0), "night"),
        ("Tue 01:00", datetime(2026, 10, 27, 1, 0), "night"), ("Fri 21:00", datetime(2026, 10, 30, 21, 0), "closed"),
        ("Wed before Thanksgiving 21:00 (GTH runs into Thursday morning)", datetime(2026, 11, 25, 21, 0), "night"),
        ("Thanksgiving 01:00", datetime(2026, 11, 26, 1, 0), "night"), ("Thanksgiving 10:00 (GTH until 11:30)", datetime(2026, 11, 26, 10, 0), "pre"),
        ("Thanksgiving 13:00", datetime(2026, 11, 26, 13, 0), "closed"), ("Thanksgiving 21:00 (for Friday)", datetime(2026, 11, 26, 21, 0), "night"),
        ("MLK Day 2027 10:00", datetime(2027, 1, 18, 10, 0), "pre"), ("MLK Day 2027 21:00", datetime(2027, 1, 18, 21, 0), "night"),
        ("Thu before Good Friday 21:00", datetime(2026, 4, 2, 21, 0), "closed"), ("Good Friday 10:00", datetime(2026, 4, 3, 10, 0), "closed"),
        ("Christmas Eve 21:00", datetime(2026, 12, 24, 21, 0), "closed"), ("New Year's Day 10:00", datetime(2026, 1, 1, 10, 0), "closed"),
        ("New Year's Day 21:00 (for Friday)", datetime(2026, 1, 1, 21, 0), "night"),
        ("Juneteenth 2026 (Fri) 10:00", datetime(2026, 6, 19, 10, 0), "pre"), ("Juneteenth 2026 21:00", datetime(2026, 6, 19, 21, 0), "closed")]:
    got = session_mode(t.replace(tzinfo=NY))
    fails += got != want
    print(("ok  " if got == want else "FAIL"), "runs:", name, "" if got == want else got)
print("all good" if not fails else f"{fails} failed")
sys.exit(1 if fails else 0)
