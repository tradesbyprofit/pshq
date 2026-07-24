"""
market_hours.py — Is the forex market open right now (UTC)?
Forex opens Sunday 22:00 UTC and closes Friday 21:00 UTC (24/5).
"""
import datetime as dt


def is_forex_open(when_utc: dt.datetime = None) -> bool:
    when = when_utc or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    wd = when.weekday()  # Mon=0 ... Sun=6
    h = when.hour
    if wd == 6 and h >= 22:          # Sunday after 22:00
        return True
    if 0 <= wd <= 3:                 # Mon–Thu, all day
        return True
    if wd == 4 and h < 21:           # Friday before 21:00
        return True
    return False


if __name__ == "__main__":
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    print(f"Now (UTC): {now:%Y-%m-%d %H:%M}  ->  forex {'OPEN ✅' if is_forex_open(now) else 'CLOSED ❌ (weekend/rollover)'}")
