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

    @patch('services.youtube_service.yt_dlp.YoutubeDL')
    def test_validate_single_vod_exception(self, mock_ydl):
        # Mock extract_info to raise an exception
        mock_instance = mock_ydl.return_value.__enter__.return_value
        mock_instance.extract_info.side_effect = Exception("Mocked exception")

        test_vod = {'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'}
        result = validate_single_vod(test_vod)

        # Function should catch exception and return None
        self.assertIsNone(result)

    @patch('services.youtube_service.check_captions_exist')
    @patch('services.youtube_service.yt_dlp.YoutubeDL')
    @patch('services.youtube_service.datetime')
    def test_validate_single_vod_success(self, mock_datetime, mock_ydl, mock_check_captions):
        # Mock vertical video dimensions
        mock_instance = mock_ydl.return_value.__enter__.return_value
        mock_instance.extract_info.return_value = {'width': 1080, 'height': 1920}

        # Mock captions available
        mock_check_captions.return_value = True

        # Mock datetime for today's date format
        mock_datetime.today.return_value.strftime.return_value = '2023-10-27'

        test_vod = {
            'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'id': 'dQw4w9WgXcQ',
            'title': 'Test Title',
            'upload_date': '20231026',
            'uploader': 'Test Creator'
        }
        result = validate_single_vod(test_vod)

        # Should survive all checks and return formatted dictionary
        expected_result = {
            'title': 'Test Title',
            'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'date': '2023-10-26',
            'creator': 'Test Creator'
        }
        self.assertEqual(result, expected_result)

    @patch('services.youtube_service.yt_dlp.YoutubeDL')
    def test_validate_single_vod_horizontal(self, mock_ydl):
        # Mock horizontal video dimensions
        mock_instance = mock_ydl.return_value.__enter__.return_value
        mock_instance.extract_info.return_value = {'width': 1920, 'height': 1080}

        test_vod = {'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'}
        result = validate_single_vod(test_vod)

        # Should discard and return None
        self.assertIsNone(result)

    @patch('services.youtube_service.check_captions_exist')
    @patch('services.youtube_service.yt_dlp.YoutubeDL')
    def test_validate_single_vod_no_captions(self, mock_ydl, mock_check_captions):
        # Mock vertical video dimensions
        mock_instance = mock_ydl.return_value.__enter__.return_value
        mock_instance.extract_info.return_value = {'width': 1080, 'height': 1920}

        # Mock captions missing
        mock_check_captions.return_value = False

        test_vod = {'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'}
        result = validate_single_vod(test_vod)

        # Should discard and return None
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
