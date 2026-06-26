import pytest
from utils.filenames import clean_filename, build_clip_filename

class TestCleanFilename:
    def test_happy_path(self):
        assert clean_filename("valid_filename_123") == "valid_filename_123"

    def test_removes_illegal_characters(self):
        assert clean_filename("test\\/*?:\"<>|file") == "testfile"
        assert clean_filename("a/b\\c*d?e:f\"g<h>i|j") == "abcdefghij"

    def test_strips_whitespace(self):
        assert clean_filename("  test file  ") == "test file"

    def test_handles_non_string_input(self):
        assert clean_filename(12345) == "12345"
        assert clean_filename(None) == "None"


class TestBuildClipFilename:
    def test_full_dictionary_input(self):
        row = {
            "Title": "Epic Gameplay",
            "Viral Score": "95%",
            "Live Title": "Stream 1"
        }
        assert build_clip_filename(row, "default_sheet") == "Epic Gameplay_95_Stream 1.mp4"

    def test_missing_keys_uses_defaults(self):
        row = {}
        assert build_clip_filename(row, "My Default Sheet") == "Untitled Clip_0_My Default Sheet.mp4"

    def test_cleans_percent_in_viral_score(self):
        row = {
            "Title": "Test",
            "Viral Score": "100%",
            "Live Title": "Test Stream"
        }
        assert build_clip_filename(row, "Active Sheet") == "Test_100_Test Stream.mp4"

    def test_sanitizes_complex_inputs_with_illegal_characters(self):
        row = {
            "Title": "What? A great play: <Wow>",
            "Viral Score": "80%*",
            "Live Title": "Stream/Part|1"
        }
        # ? : < > * / | should be removed
        # What? A great play: <Wow> -> What A great play Wow
        # 80%* -> 80
        # Stream/Part|1 -> StreamPart1
        assert build_clip_filename(row, "Active Sheet") == "What A great play Wow_80_StreamPart1.mp4"

    def test_handles_leading_trailing_whitespace_in_values(self):
        row = {
            "Title": "  Spaces  ",
            "Viral Score": " 50% ",
            "Live Title": "  Live  "
        }
        assert build_clip_filename(row, "Active Sheet") == "Spaces_50_Live.mp4"
