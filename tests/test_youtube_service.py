import unittest
from unittest.mock import patch
from services.youtube_service import extract_youtube_id, validate_single_vod

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

    def test_validate_single_vod_horizontal(self):
        test_vod = {
            'id': 'test',
            'title': 'Test VOD',
            'live_status': 'was_live',
            'width': 1920,
            'height': 1080,
            'automatic_captions': None
        }
        self.assertIsNone(validate_single_vod(test_vod))

    def test_validate_single_vod_no_captions(self):
        test_vod = {
            'id': 'test',
            'title': 'Test VOD',
            'live_status': 'was_live',
            'width': 1080,
            'height': 1920,
            'automatic_captions': None
        }
        self.assertIsNone(validate_single_vod(test_vod))

    def test_validate_single_vod_success(self):
        test_vod = {
            'id': 'dQw4w9WgXcQ',
            'title': 'Test Title',
            'live_status': 'was_live',
            'width': 1080,
            'height': 1920,
            'automatic_captions': {
                'en': [{'name': 'English', 'ext': 'vtt', 'url': 'http://example.com/vtt'}]
            },
            'webpage_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'uploader': 'Test Creator',
            'upload_date': '20231026'
        }
        result = validate_single_vod(test_vod)

        self.assertIsNotNone(result)
        self.assertEqual(result.title, 'Test Title')
        self.assertEqual(result.url, 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        self.assertEqual(result.date, '2023-10-26')
        self.assertEqual(result.creator, 'Test Creator')
        self.assertEqual(result.captions_url, 'http://example.com/vtt')
        self.assertEqual(result.video_id, 'dQw4w9WgXcQ')

if __name__ == '__main__':
    unittest.main()
