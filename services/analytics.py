"""Read-only analytics over existing logs; no device state changes."""
import json
from datetime import datetime, timedelta

DEVICES = ('light', 'fan', 'door')


def recorded_state(log, device):
    if getattr(log, 'value', None) == 'command_failed':
        return None
    raw = log.status
    try:
        state = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        state = raw
    if isinstance(state, dict):
        key = 'locked' if device == 'door' else 'on'
        value = state.get(key)
        if isinstance(value, bool):
            return not value if device == 'door' else value
        return None  # An accepted door command is not a position measurement.
    if isinstance(state, str):
        state = state.lower()
        if state in ('on', 'unlocked', 'open'):
            return True
        if state in ('off', 'locked', 'closed'):
            return False
    return None


def device_summary(logs, lighting):
    result = {}
    for device in DEVICES:
        rows = [row for row in logs if row.device_name == device]
        source = 'device_status_logs'
        if device == 'light' and not rows:
            rows = list(lighting)
            source = 'lighting_records'
        states = [recorded_state(row, device) for row in rows]
        on = sum(value is True for value in states)
        off = sum(value is False for value in states)
        result[device] = dict(total_logs=len(rows), on_count=on, off_count=off,
            unknown_count=len(rows)-on-off,
            accepted_count=sum(getattr(row, 'value', None) == 'accepted' for row in rows),
            failed_count=sum(getattr(row, 'value', None) == 'command_failed' for row in rows),
            on_ratio=round(on / max(len(rows), 1) * 100, 1), data_source=source)
    return result


def lighting_intervals(records, since, until):
    """Count only intervals bounded by recorded observations, clipped to the window.

    Repeated ON/brightness updates split intervals without double counting. Never
    extrapolate an unclosed final ON to wall-clock now (the board may be offline).
    A missing initial ON gives no inferred time. Unknown records break continuity.
    """
    previous = None
    intervals = []
    rows = sorted((r for r in records if r.recorded_at <= until),
                  key=lambda r: (r.recorded_at, getattr(r, 'id', 0) or 0))
    for row in rows:
        state = recorded_state(row, 'light')
        if previous is not None and state is not None:
            if recorded_state(previous, 'light') is True:
                start, end = max(since, previous.recorded_at), min(until, row.recorded_at)
                if end > start:
                    brightness = max(0, min(100, previous.brightness or 0))
                    intervals.append((start, end, brightness))
        previous = row if state is not None else None
    pending = previous is not None and recorded_state(previous, 'light') is True
    return intervals, pending


def lighting_totals(intervals):
    seconds = sum((end-start).total_seconds() for start,end,_ in intervals)
    # Retain existing 60 W full-brightness estimate; this is not a power measurement.
    energy = sum((end-start).total_seconds()*60*brightness/100/3600
                 for start,end,brightness in intervals)
    return round(seconds, 3), round(energy, 2)


def lighting_daily(records, since, until):
    intervals, _ = lighting_intervals(records, since, until)
    daily = {}
    def day_entry(day):
        return daily.setdefault(day, {'date': day, 'seconds': 0, 'energy': 0,
                                      'turn_on_count': 0, 'brightness': []})
    for row in records:
        if since <= row.recorded_at <= until:
            entry = day_entry(row.recorded_at.strftime('%Y-%m-%d'))
            if row.status == 'on':
                entry['turn_on_count'] += 1
                entry['brightness'].append(row.brightness or 0)
    for start,end,brightness in intervals:
        while start < end:
            stop = min(end, datetime.combine(start.date()+timedelta(days=1), datetime.min.time()))
            seconds = (stop-start).total_seconds()
            entry = day_entry(start.strftime('%Y-%m-%d'))
            entry['seconds'] += seconds
            entry['energy'] += seconds*60*brightness/100/3600
            start = stop
    return [dict(date=day, total_on_seconds=round(d['seconds'], 3),
                 total_on_hours=round(d['seconds']/3600, 4),
                 turn_on_count=d['turn_on_count'], energy_wh=round(d['energy'], 2),
                 avg_brightness=round(sum(d['brightness'])/len(d['brightness']), 1) if d['brightness'] else 0)
            for day,d in sorted(daily.items())]
