import pytest
from utils.timestamps import timestamp_to_seconds

@pytest.mark.parametrize("ts_str, expected", [
    # 3 parts (HH:MM:SS)
    ("1:02:03", 3723),
    ("00:00:00", 0),
    ("2:30:00", 9000),
    # 2 parts (MM:SS)
    ("05:00", 300),
    ("1:30", 90),
    ("00:45", 45),
    # 1 part
    ("60", 0),
    # 4 parts
    ("1:02:03:04", 0),
    # Empty and None
    ("", 0),
    (None, 0),
    # Invalid characters that are stripped out
    ("1h:30m", 90),
    ("abc", 0),
    (" 1:02 ", 62),
    # Missing colons
    ("1234", 0),
])
def test_timestamp_to_seconds_valid_and_edge_cases(ts_str, expected):
    assert timestamp_to_seconds(ts_str) == expected

def test_timestamp_to_seconds_raises_value_error_on_empty_parts():
    # If the string contains consecutive colons or trailing colons,
    # int('') will raise ValueError based on the current implementation.
    with pytest.raises(ValueError):
        timestamp_to_seconds("1::30")

    with pytest.raises(ValueError):
        timestamp_to_seconds(":")
