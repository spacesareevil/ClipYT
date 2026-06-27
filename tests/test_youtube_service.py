import unittest
import urllib.error
from unittest.mock import patch
from services.youtube_service import extract_youtube_id, check_captions_exist

class TestYoutubeService(unittest.TestCase):
    @patch('services.youtube_service.logger')
    @patch('urllib.request.urlopen')
    def test_check_captions_exist_url_error(self, mock_urlopen, mock_logger):
        # Arrange
        mock_urlopen.side_effect = urllib.error.URLError("Network unreachable")
        video_id = "test_video_id"

        # Act
        result = check_captions_exist(video_id)

        # Assert
        self.assertFalse(result)
        mock_logger.warning.assert_called_once()
        self.assertIn("Innertube API check failed", mock_logger.warning.call_args[0][0])

    @patch('services.youtube_service.logger')
    @patch('urllib.request.urlopen')
    def test_check_captions_exist_timeout_error(self, mock_urlopen, mock_logger):
        # Arrange
        mock_urlopen.side_effect = TimeoutError("Connection timed out")
        video_id = "test_video_id"

        # Act
        result = check_captions_exist(video_id)

        # Assert
        self.assertFalse(result)
        mock_logger.warning.assert_called_once()
        self.assertIn("Innertube API check failed", mock_logger.warning.call_args[0][0])

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

if __name__ == '__main__':
    unittest.main()
