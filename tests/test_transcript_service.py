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
