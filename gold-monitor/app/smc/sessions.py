"""Session & Killzone management for institutional Forex / Gold trading."""
from datetime import datetime, timezone, time
from typing import Dict, Any, Tuple
from app.config import USE_KILLZONES, LONDON_KZ_START, LONDON_KZ_END, NY_KZ_START, NY_KZ_END

def parse_time_str(t_str: str) -> time:
    parts = t_str.strip().split(":")
    return time(hour=int(parts[0]), minute=int(parts[1]))

LONDON_START = parse_time_str(LONDON_KZ_START)
LONDON_END = parse_time_str(LONDON_KZ_END)
NY_START = parse_time_str(NY_KZ_START)
NY_END = parse_time_str(NY_KZ_END)

# Institutional Rule: Avoid London opening manipulation window 12:30 PM to 1:45 PM IST (07:00 to 08:15 UTC)
LONDON_BLACKOUT_START = time(7, 0)   # 12:30 PM IST
LONDON_BLACKOUT_END = time(8, 15)     # 01:45 PM IST

def get_session_info(dt: datetime, v2_rules: bool = False) -> Dict[str, Any]:
    """
    Returns session classification for all 4 major sessions.
    Under V2 institutional rules:
    - Allows trading across Asian, London, New York AM, and NY PM/Sydney sessions.
    - STRICTLY BLOCKS trading during London Open Blackout: 12:30 PM to 1:45 PM IST (07:00 to 08:15 UTC).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    t = dt.time()
    weekday = dt.weekday()  # 0=Monday, 4=Friday, 5=Saturday, 6=Sunday

    is_weekend = weekday >= 5 or (weekday == 4 and t >= time(21, 0)) or (weekday == 6 and t < time(21, 0))

    in_london_blackout = (LONDON_BLACKOUT_START <= t < LONDON_BLACKOUT_END) and weekday < 5

    # 4 Major Sessions
    is_asian = (time(0, 0) <= t < time(7, 0)) and weekday < 5
    is_london = (LONDON_BLACKOUT_END <= t < time(12, 30)) and weekday < 5
    is_ny_am = (time(12, 30) <= t < time(16, 30)) and weekday < 5
    is_ny_pm = (time(16, 30) <= t < time(21, 0)) and weekday < 5
    is_sydney = (time(21, 0) <= t <= time(23, 59, 59)) and weekday < 5

    if not v2_rules:
        in_london_legacy = (LONDON_START <= t <= LONDON_END) and weekday < 5
        in_ny_legacy = (NY_START <= t <= NY_END) and weekday < 5
        session_name = "OFF_HOURS"
        if in_london_legacy:
            session_name = "LONDON_OPEN_KILLZONE"
        elif in_ny_legacy:
            session_name = "NEW_YORK_AM_KILLZONE"
        elif time(0, 0) <= t < time(7, 0):
            session_name = "ASIAN_SESSION"
        elif time(10, 0) < t < time(12, 30):
            session_name = "LONDON_LUNCH"
        elif time(15, 30) < t < time(21, 0):
            session_name = "NY_PM_SESSION"

        is_active_kz = in_london_legacy or in_ny_legacy
        allowed_to_trade = is_active_kz if USE_KILLZONES else not is_weekend
        reason = f"Active in {session_name}" if allowed_to_trade else ("Weekend closed" if is_weekend else "Outside London/NY Killzones")
    else:
        session_name = "OFF_HOURS"
        if in_london_blackout:
            session_name = "LONDON_OPEN_BLACKOUT (12:30-1:45 PM IST)"
        elif is_asian:
            session_name = "ASIAN_SESSION"
        elif is_london:
            session_name = "LONDON_SESSION"
        elif is_ny_am:
            session_name = "NEW_YORK_AM_SESSION"
        elif is_ny_pm:
            session_name = "NEW_YORK_PM_SESSION"
        elif is_sydney:
            session_name = "SYDNEY_TOKYO_SESSION"

        allowed_to_trade = not is_weekend and not in_london_blackout and (is_asian or is_london or is_ny_am or is_ny_pm or is_sydney)
        is_active_kz = allowed_to_trade
        if in_london_blackout:
            reason = "AVOID_LONDON_OPEN: 12:30 PM - 1:45 PM IST Judas swing manipulation trap window"
        elif is_weekend:
            reason = "Weekend market closed"
        else:
            reason = f"Active in {session_name}"

    return {
        "timestamp_utc": dt.isoformat(),
        "weekday": weekday,
        "session": session_name,
        "is_killzone": is_active_kz,
        "is_weekend": is_weekend,
        "in_london_blackout": in_london_blackout,
        "allowed_to_trade": allowed_to_trade,
        "reason": reason
    }
