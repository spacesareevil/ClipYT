import pytest
from utils.filenames import clean_filename, build_clip_filename

def test_clean_filename():
    # Test stripping of whitespace
    assert clean_filename("  test  ") == "test"

    # Test removal of invalid characters \/*?:"<>|
    assert clean_filename(r'a\b/c*d?e:f"g<h>i|j') == "abcdefghij"

    # Test with string casting
    assert clean_filename(12345) == "12345"
    assert clean_filename(None) == "None"

def test_build_clip_filename():
    # Test with all fields provided
    row = {
        "Title": "My Awesome Clip",
        "Viral Score": "99%",
        "Live Title": "Epic Live Stream"
    }
    assert build_clip_filename(row, "Default Live") == "My Awesome Clip_99_Epic Live Stream.mp4"

    # Test with missing fields, fallback to defaults
    row = {}
    assert build_clip_filename(row, "Default Live") == "Untitled Clip_0_Default Live.mp4"

    # Test with invalid characters
    row = {
        "Title": "My <Awesome> Clip: Part 1",
        "Viral Score": "50%?",
        "Live Title": "Live | Stream"
    }
    assert build_clip_filename(row, "Default Live") == "My Awesome Clip Part 1_50_Live  Stream.mp4"

    # Test whitespaces stripping in values
    row = {
        "Title": "   Padded Title   ",
        "Viral Score": "  80%  ",
        "Live Title": "  Padded Live Title  "
    }
    assert build_clip_filename(row, "Default Live") == "Padded Title_80_Padded Live Title.mp4"
