import os
import logging
import subprocess
import yt_dlp
from utils.timestamps import timestamp_to_seconds

logger = logging.getLogger(__name__)

def download_video_section(video_url: str, start_time: str, end_time: str, local_output_path: str):
    """
    Downloads a specific section of a YouTube video using yt-dlp and ffmpeg,
    utilizing NVIDIA hardware acceleration (NVENC) for optimal performance.
    Implements local caching to avoid redundant downloads.
    """
    if os.path.exists(local_output_path):
        logger.info(f"Cache hit: {local_output_path} already exists. Skipping download.")
        return

    logger.info(f"Starting yt-dlp section download: {video_url} [{start_time} -> {end_time}]")

    t_start = timestamp_to_seconds(start_time)
    t_end = timestamp_to_seconds(end_time)

    def download_range_func(info_dict, ydl):
        return [{
            'start_time': t_start,
            'end_time': t_end,
        }]

    ydl_opts = {
        'download_ranges': download_range_func,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': local_output_path,
        'external_downloader': 'ffmpeg',
        'external_downloader_args': {
            'ffmpeg_i': ['-hwaccel', 'cuda'],
            'ffmpeg_o': ['-c:v', 'h264_nvenc', '-preset', 'p6']
        },
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        logger.info(f"Successfully downloaded section to: {local_output_path}")
    except Exception as e:
        logger.error(f"yt-dlp targeted download failed for {local_output_path}. Error: {str(e)}")
        raise


def slice_local_vod(local_vod_path: str, start_time: str, end_time: str, local_output_path: str):
    logger.info(f"Starting FFmpeg clip generation: {start_time} -> {end_time}")
    t_start = timestamp_to_seconds(start_time)
    t_end = timestamp_to_seconds(end_time)
    duration = t_end - t_start

    command = [
        'ffmpeg', '-y',
        '-ss', str(t_start),
        '-i', local_vod_path,
        '-t', str(duration),
        '-c:v', 'copy', '-c:a', 'copy',
        local_output_path
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        logger.info(f"FFmpeg successfully sliced clip to: {local_output_path}")
    except Exception as e:
        logger.error(f"FFmpeg slicing failed for {local_output_path}. Error: {str(e)}")
        raise

def write_metadata_text_file(row: dict, txt_path: str):
    logger.info(f"Writing metadata text payload to: {txt_path}")
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f"Title: {row.get('Title', '')}\n")
        f.write(f"Description: {row.get('Description', '')}\n")
        f.write(f"Hashtags: {row.get('Hashtags', '')}\n")
        
        # New Agentic QA Block
        if "QA Grade" in row:
            f.write("\n--- AGENTIC QA REVIEW ---\n")
            f.write(f"Grade: {row.get('QA Grade', 'N/A')}\n")
            f.write(f"Match: {row.get('QA Is Match', 'N/A')}\n")
            f.write(f"Visual Description: {row.get('QA Visual Description', '')}\n")
            f.write(f"Feedback: {row.get('QA Feedback', '')}\n")