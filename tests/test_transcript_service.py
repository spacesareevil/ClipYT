import pytest
from services.transcript_service import TranscriptService

@pytest.fixture
def service():
    return TranscriptService()

def test_clean_text_basic(service):
    """Test basic string with no special characters."""
    assert service._clean_text("hello world") == "hello world"

def test_clean_text_newlines(service):
    """Test string with newlines."""
    assert service._clean_text("hello\nworld") == "hello world"
    assert service._clean_text("hello\n\nworld") == "hello world"

def test_clean_text_multiple_spaces(service):
    """Test string with multiple spaces and tabs."""
    assert service._clean_text("hello   world") == "hello world"
    assert service._clean_text("hello\tworld") == "hello world"
    assert service._clean_text("hello \t world") == "hello world"

def test_clean_text_leading_trailing(service):
    """Test string with leading and trailing whitespace."""
    assert service._clean_text("  hello world  ") == "hello world"
    assert service._clean_text("\nhello world\n") == "hello world"
    assert service._clean_text("\t\thello world\t\t") == "hello world"

def test_clean_text_mixed_whitespace(service):
    """Test string with mixed whitespace characters."""
    assert service._clean_text("  hello \n \t  world \n \n ") == "hello world"

def test_clean_text_empty(service):
    """Test empty strings and strings with only whitespace."""
    assert service._clean_text("") == ""
    assert service._clean_text("   ") == ""
    assert service._clean_text("\n\t  \n") == ""

def test_filter_empty_list(service):
    """Test with an empty transcript list."""
    assert service._filter_by_speech_density([]) == []

def test_filter_drops_low_density_chunk(service):
    """Test dropping a chunk with fewer than the minimum words."""
    transcript = [
        {"start": 0, "text": "This is a short text with just a few words."},
        {"start": 100, "text": "Another short sentence."},
    ]
    # Total 12 words, less than default 50
    assert service._filter_by_speech_density(transcript) == []

def test_filter_keeps_high_density_chunk(service):
    """Test keeping a chunk with enough words."""
    word = "word "
    transcript = [
        {"start": 0, "text": word * 30},
        {"start": 100, "text": word * 20},
    ]
    # Total 50 words, equals default 50
    res = service._filter_by_speech_density(transcript)
    assert len(res) == 2
    assert res == transcript

def test_filter_mixed_chunks(service):
    """Test with a mix of high and low density chunks."""
    word = "word "
    transcript = [
        # Chunk 0 (0-299): 50 words - keep
        {"start": 0, "text": word * 50},
        # Chunk 1 (300-599): 10 words - drop
        {"start": 350, "text": word * 10},
        # Chunk 2 (600-899): 60 words - keep
        {"start": 650, "text": word * 60},
    ]
    res = service._filter_by_speech_density(transcript)
    assert len(res) == 2
    assert res[0]["start"] == 0
    assert res[1]["start"] == 650

def test_filter_custom_parameters(service):
    """Test overriding chunk_sec and min_words parameters."""
    word = "word "
    transcript = [
        # Chunk 0 (0-59): 10 words - keep
        {"start": 0, "text": word * 10},
        # Chunk 1 (60-119): 5 words - drop
        {"start": 65, "text": word * 5},
    ]
    # Custom parameters: chunk_sec=60, min_words=10
    res = service._filter_by_speech_density(transcript, chunk_sec=60, min_words=10)
    assert len(res) == 1
    assert res[0]["start"] == 0

def test_filter_object_attributes(service):
    """Test using objects with attributes instead of dictionaries."""
    class MockEntry:
        def __init__(self, start, text):
            self.start = start
            self.text = text

        def get(self, key, default=None):
            return getattr(self, key, default)

    word = "word "
    transcript = [
        MockEntry(0, word * 50),
        MockEntry(350, word * 10),
    ]
    res = service._filter_by_speech_density(transcript)
    assert len(res) == 1
    assert res[0].start == 0
