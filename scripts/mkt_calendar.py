"""US market calendar for the realtime updates: NYSE/Cboe full holidays and early closes.

Weekends and these days have no session; on early-close days the cash market closes at 13:00 ET and SPX options at
13:15. Extend the lists each year (NYSE publishes them years ahead).
"""
from datetime import date

HOLIDAYS = {
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
    # 2027
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 31), date(2027, 6, 18),
    date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25), date(2027, 12, 24),
}
EARLY_CLOSE = {date(2026, 11, 27), date(2026, 12, 24), date(2027, 11, 26)}


def is_trading_day(d):
    return d.weekday() < 5 and d not in HOLIDAYS


def options_close_minutes(d):
    """When SPX options stop trading that day (minutes after midnight, New York)."""
    return 13 * 60 + 15 if d in EARLY_CLOSE else 16 * 60 + 15
