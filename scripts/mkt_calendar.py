"""US market calendar for the realtime updates: NYSE/Cboe full holidays and early closes, computed from NYSE's rules
for any year (no list to keep up to date), and when the updates should run.

Cboe's global trading hours (GTH) for SPX/VIX options keep running on most holidays: from 20:15 ET the evening before
until 11:30 ET on the holiday, and again from 20:15 that evening when the next day trades. They do not run on Good
Friday or Christmas Day, nor on the morning of New Year's Day (Cboe, "Hours & Holidays").

Weekends and these days have no session; on early-close days the cash market closes at 13:00 ET and SPX options at
13:15. One-off closures (a national day of mourning, say) cannot be computed: add them to EXTRA_CLOSED.
"""
from datetime import date, timedelta
from functools import lru_cache

EXTRA_CLOSED = set()  # one-off closures, e.g. date(2025, 1, 9) (President Carter's national day of mourning)


def _nth_weekday(y, m, wd, n):
    """The n-th weekday `wd` (Mon=0) of the month; n=-1 for the last."""
    if n > 0:
        d = date(y, m, 1)
        d += timedelta(days=(wd - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(y, m + 1, 1) - timedelta(days=1) if m < 12 else date(y, 12, 31)
    return d - timedelta(days=(d.weekday() - wd) % 7)


def _easter(y):
    """Western Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return date(y, month, day)


def _observed(d):
    """A fixed-date holiday on Saturday is kept on Friday, on Sunday on Monday."""
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d


@lru_cache(maxsize=None)
def holidays(y):
    out = {
        _nth_weekday(y, 1, 0, 3),            # Martin Luther King Jr. Day
        _nth_weekday(y, 2, 0, 3),            # Washington's Birthday
        _easter(y) - timedelta(days=2),      # Good Friday
        _nth_weekday(y, 5, 0, -1),           # Memorial Day
        _observed(date(y, 7, 4)),            # Independence Day
        _nth_weekday(y, 9, 0, 1),            # Labor Day
        _nth_weekday(y, 11, 3, 4),           # Thanksgiving
        _observed(date(y, 12, 25)),          # Christmas
    }
    if y >= 2022:
        out.add(_observed(date(y, 6, 19)))   # Juneteenth (from 2022)
    # New Year's Day: on Sunday it moves to Monday; on Saturday NYSE does not close the Friday before
    ny = date(y, 1, 1)
    if ny.weekday() == 6:
        out.add(ny + timedelta(days=1))
    elif ny.weekday() < 5:
        out.add(ny)
    return frozenset(out)


@lru_cache(maxsize=None)
def early_closes(y):
    """13:00 closes: the day after Thanksgiving, Christmas Eve and July 3 when they are trading days."""
    out = {_nth_weekday(y, 11, 3, 4) + timedelta(days=1)}
    for d in (date(y, 12, 24), date(y, 7, 3)):
        if d.weekday() < 5 and d not in holidays(y):
            out.add(d)
    return frozenset(out)


def is_trading_day(d):
    return d.weekday() < 5 and d not in holidays(d.year) and d not in EXTRA_CLOSED


def options_close_minutes(d):
    """When SPX options stop trading that day (minutes after midnight, New York)."""
    return 13 * 60 + 15 if d in early_closes(d.year) else 16 * 60 + 15


def gth_morning_holiday(d):
    """A holiday on whose morning GTH runs (until 11:30 ET): all but Good Friday, Christmas and New Year's Day."""
    if d not in holidays(d.year):
        return False
    y = d.year
    return d not in {_easter(y) - timedelta(days=2), _observed(date(y, 12, 25)), date(y, 1, 1), date(y, 1, 2)}


def _evening_session(d):
    """Whether an overnight session starts at 20:15 on day d: GTH opens for a next day that trades or has a GTH
    morning; never on Saturday or Sunday (after a weekend Cboe's delayed quotes stay stale until 3:15 ET Monday),
    Good Friday or Christmas."""
    if d.weekday() >= 5 or d in {_easter(d.year) - timedelta(days=2), _observed(date(d.year, 12, 25))}:
        return False
    nxt = d + timedelta(days=1)
    return is_trading_day(nxt) or gth_morning_holiday(nxt)


def session_mode(now=None):
    """open: the regular session until the official SKEW is in (update every 5 minutes); pre: VIX's extended session
    from 3:00 ET (every 5 minutes), also on a holiday's GTH morning until 11:30; night: an overnight session from 20:15
    ET (every 15 minutes); closed: no session (one update, then stop)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    n = now or datetime.now(ZoneInfo("America/New_York"))
    d, m = n.date(), n.hour * 60 + n.minute
    td = is_trading_day(d)
    if td and 9 * 60 + 15 <= m < 17 * 60 + 20:
        return "open"
    if (td and 3 * 60 <= m < 9 * 60 + 15) or (gth_morning_holiday(d) and 3 * 60 <= m < 11 * 60 + 30):
        return "pre"
    if m >= 20 * 60 + 15 and _evening_session(d):
        return "night"
    if m < 3 * 60 and (td or gth_morning_holiday(d)) and _evening_session(d - timedelta(days=1)):
        return "night"
    return "closed"
