import re

def timestamp_to_seconds(ts_str: str) -> int:
    sanitized_ts = re.sub(r'[^0-9:]', '', str(ts_str)).strip()
    if not sanitized_ts: return 0
    parts = list(map(int, sanitized_ts.split(':')))
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return 0

def natural_sort_key(value):
    text = str(value).replace('%', '')
    try: return float(text)
    except ValueError: return text.lower()