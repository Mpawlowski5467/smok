from datetime import UTC, datetime

from timestamps import as_utc

assert as_utc("2025-01-01T01:30:00+02:00") == datetime(2024, 12, 31, 23, 30, tzinfo=UTC)
assert as_utc("2025-05-01T12:00:00-03:30") == datetime(2025, 5, 1, 15, 30, tzinfo=UTC)
assert as_utc("2025-01-01T00:00:00Z").tzinfo is UTC
assert as_utc("2025-01-01T00:00:00") == datetime(2025, 1, 1, tzinfo=UTC)
try:
    as_utc("not-a-date")
except ValueError:
    pass
else:
    raise AssertionError("invalid timestamp accepted")
