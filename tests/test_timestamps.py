import pytest
from utils.timestamps import timestamp_to_seconds, natural_sort_key

def test_timestamp_to_seconds_hh_mm_ss():
    assert timestamp_to_seconds("1:01:01") == 3661
    assert timestamp_to_seconds("01:00:00") == 3600
    assert timestamp_to_seconds("00:00:00") == 0

def test_timestamp_to_seconds_mm_ss():
    assert timestamp_to_seconds("02:30") == 150
    assert timestamp_to_seconds("00:45") == 45
    assert timestamp_to_seconds("59:59") == 3599

def test_timestamp_to_seconds_invalid_format():
    # Only single part or empty after sanitation
    assert timestamp_to_seconds("10") == 0
    assert timestamp_to_seconds("abc") == 0
    assert timestamp_to_seconds("") == 0

def test_timestamp_to_seconds_with_junk():
    assert timestamp_to_seconds(" 12:34 ") == 754
    assert timestamp_to_seconds("abc12:34xyz") == 754

def test_natural_sort_key_percentage():
    assert natural_sort_key("50%") == 50.0
    assert natural_sort_key("100%") == 100.0
    assert natural_sort_key("0%") == 0.0

def test_natural_sort_key_float():
    assert natural_sort_key("10.5") == 10.5
    assert natural_sort_key("-5.2") == -5.2
    assert natural_sort_key(42) == 42.0

def test_natural_sort_key_text():
    assert natural_sort_key("Banana") == "banana"
    assert natural_sort_key("apple") == "apple"
    assert natural_sort_key("CHERRY") == "cherry"

def test_natural_sort_key_sorting():
    # Mix of percentages and float strings
    values = ["50%", "10.5", "100%", "2.5", "30"]
    sorted_values = sorted(values, key=natural_sort_key)
    assert sorted_values == ["2.5", "10.5", "30", "50%", "100%"]

    # Mix of strings
    text_values = ["banana", "Apple", "cherry"]
    sorted_text_values = sorted(text_values, key=natural_sort_key)
    assert sorted_text_values == ["Apple", "banana", "cherry"]
