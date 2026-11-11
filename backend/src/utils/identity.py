import uuid
from datetime import datetime, timezone
def new_id(prefix):
    return prefix + "-" + uuid.uuid4().hex[:12]
def now():
    return datetime.now(timezone.utc).isoformat()
def parse_ts(value):
    if not value: return None
    try:
        return datetime.fromisoformat(value.replace("Z","+00:00"))
    except (TypeError, ValueError):
        return None
def age_seconds(value, at=None):
    ts=parse_ts(value)
    if ts is None: return None
    if at is None: at=datetime.now(timezone.utc)
    return (at-ts).total_seconds()
