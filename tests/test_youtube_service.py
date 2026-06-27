import unittest
import json
from unittest.mock import patch, MagicMock
from services.youtube_service import extract_youtube_id, check_captions_exist

class TestYoutubeService(unittest.TestCase):
    def test_extract_youtube_id_valid_urls(self):
        valid_cases = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("http://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("http://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/v/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=youtu.be", "dQw4w9WgXcQ"),
            ("dQw4w9WgXcQ", None), # Should not match just the ID
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=43s", "dQw4w9WgXcQ")
        ]

        for url, expected_id in valid_cases:
            with self.subTest(url=url):
                self.assertEqual(extract_youtube_id(url), expected_id)

    def test_extract_youtube_id_invalid_urls(self):
        invalid_cases = [
            "https://www.google.com",
            "https://vimeo.com/123456789",
            "not a url",
            "",
            "https://www.youtube.com/watch?v=too_short", # invalid id format
            "https://www.youtube.com/watch?v=too_looooong", # invalid id format (will match first 11)
            None
        ]

        for url in invalid_cases:
            with self.subTest(url=url):
                if url == "https://www.youtube.com/watch?v=too_looooong":
                    self.assertEqual(extract_youtube_id(url), "too_looooon")
                elif url is None:
                    with self.assertRaises(TypeError):
                        extract_youtube_id(url)
                else:
                    self.assertIsNone(extract_youtube_id(url))

    @patch('urllib.request.urlopen')
    def test_check_captions_exist_true(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "captions": {
                "playerCaptionsTracklistRenderer": {}
            }
        }).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        self.assertTrue(check_captions_exist("dQw4w9WgXcQ"))

    @patch('urllib.request.urlopen')
    def test_check_captions_exist_empty_captions(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "captions": {}
        }).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        self.assertFalse(check_captions_exist("dQw4w9WgXcQ"))

    @patch('urllib.request.urlopen')
    def test_check_captions_exist_no_captions(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "some_other_key": "value"
        }).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        self.assertFalse(check_captions_exist("dQw4w9WgXcQ"))

    @patch('urllib.request.urlopen')
    def test_check_captions_exist_exception(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Network error")

        self.assertFalse(check_captions_exist("dQw4w9WgXcQ"))

if __name__ == '__main__':
    unittest.main()
