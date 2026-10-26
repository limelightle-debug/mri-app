"""US market calendar for the realtime updates: NYSE/Cboe full holidays and early closes, computed from NYSE's rules
for any year (no list to keep up to date).

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
