import os
import unittest
from unittest.mock import patch, MagicMock
from services.clip_service import download_video_section

class TestClipService(unittest.TestCase):

    @patch('services.clip_service.os.path.exists')
    @patch('services.clip_service.yt_dlp.YoutubeDL')
    def test_download_video_section_cache_hit(self, mock_ytdl, mock_exists):
        # Arrange
        mock_exists.return_value = True
        video_url = "https://youtube.com/watch?v=123"
        start_time = "01:00"
        end_time = "02:00"
        local_output_path = "/fake/path/out.mp4"

        # Act
        download_video_section(video_url, start_time, end_time, local_output_path)

        # Assert
        mock_exists.assert_called_once_with(local_output_path)
        mock_ytdl.assert_not_called() # YoutubeDL shouldn't be invoked

    @patch('services.clip_service.os.path.exists')
    @patch('services.clip_service.yt_dlp.YoutubeDL')
    def test_download_video_section_success(self, mock_ytdl, mock_exists):
        # Arrange
        mock_exists.return_value = False
        mock_instance = MagicMock()
        # YoutubeDL is used as a context manager, so mock __enter__ to return instance
        mock_ytdl.return_value.__enter__.return_value = mock_instance

        video_url = "https://youtube.com/watch?v=123"
        start_time = "01:00"  # 60s
        end_time = "02:00"    # 120s
        local_output_path = "/fake/path/out.mp4"

        # Act
        download_video_section(video_url, start_time, end_time, local_output_path)

        # Assert
        mock_exists.assert_called_once_with(local_output_path)

        # Check that yt-dlp was initialized
        mock_ytdl.assert_called_once()
        ydl_opts = mock_ytdl.call_args[0][0]

        self.assertEqual(ydl_opts['outtmpl'], local_output_path)
        self.assertEqual(ydl_opts['external_downloader'], 'ffmpeg')
        self.assertIn('-hwaccel', ydl_opts['external_downloader_args']['ffmpeg_i'])
        self.assertIn('-c:v', ydl_opts['external_downloader_args']['ffmpeg_o'])
        self.assertIn('h264_nvenc', ydl_opts['external_downloader_args']['ffmpeg_o'])

        # Check download function was called with video url
        mock_instance.download.assert_called_once_with([video_url])

        # Test the download_range_func logic
        range_func = ydl_opts['download_ranges']
        ranges = range_func(None, None)
        self.assertEqual(ranges[0]['start_time'], 60)
        self.assertEqual(ranges[0]['end_time'], 120)

    @patch('services.clip_service.os.path.exists')
    @patch('services.clip_service.yt_dlp.YoutubeDL')
    def test_download_video_section_exception(self, mock_ytdl, mock_exists):
        # Arrange
        mock_exists.return_value = False
        mock_instance = MagicMock()
        mock_instance.download.side_effect = Exception("yt-dlp error")
        mock_ytdl.return_value.__enter__.return_value = mock_instance

        # Act & Assert
        with self.assertRaises(Exception) as context:
            download_video_section("url", "00:00", "01:00", "/fake/path/out.mp4")

        self.assertTrue("yt-dlp error" in str(context.exception))

if __name__ == '__main__':
    unittest.main()
