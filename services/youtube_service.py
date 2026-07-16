import re
import json
import logging
import subprocess
import urllib.request
import yt_dlp
import concurrent.futures
from datetime import datetime
from dataclasses import dataclass
from datetime import datetime, date as dt_date
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

@dataclass
class VerticalVodData:
    title: str
    url: str
    date: dt_date
    creator: str
    captions_url: str
    video_id: str

def extract_youtube_id(url: str) -> str:
    pattern = r'(?:v=|\/shorts\/|\/embed\/|\/v\/|youtu\.be\/|\/watch\?v=|\/live\/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def validate_single_vod(vod):
    live_status = vod['live_status']
    video_id = vod['id']
    title= vod['title']    
    
    if live_status == "is_upcoming":    #Ignore Scheduled Streams
        logger.info(f"CHECK FAILED ON {video_id}-{title[0:20]}: VOD is scheduled")
        return None
    
    if live_status == "post_live":      #Ignore lives that youtube has yet to process
        logger.info(f"CHECK FAILED ON {video_id}-{title[0:20]}: VOD processing")
        return None
        
    height = vod['height']
    width = vod['width']

    if height < width:                  #Ignore Horizontal Format (maybe make a toggle for horizontal/vertical?)
        logger.info(f"CHECK FAILED ON {video_id}-{title[0:20]}: Horizontal VOD")
        return None
    
    automatic_captions = vod.get('automatic_captions')
    subtitles = vod.get('subtitles')

    en_captions_url = None
    
    # Try manual English subtitles first
    if subtitles and "en" in subtitles:
        for sub in subtitles["en"]:
            if sub.get("ext") == "vtt":
                en_captions_url = sub.get("url")
                break

    # Fallback to automatic English captions
    if not en_captions_url and automatic_captions and "en" in automatic_captions:
        for sub in automatic_captions["en"]:
            if sub.get("ext") == "vtt":
                en_captions_url = sub.get("url")
                break

    if not en_captions_url:
        logger.info(f"CHECK FAILED ON {video_id}-{title[0:20]}: No English VTT captions found")
        return None

    raw_date = vod.get('upload_date', '')
    formatted_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}" if raw_date and len(raw_date) == 8 else datetime.today().strftime('%Y-%m-%d')
    logger.info(f"CHECK PASSED ON {video_id}-{title[0:20]}")
    return VerticalVodData(
        title = title,
        url = vod['webpage_url'],
        date = formatted_date,
        creator = vod['uploader'],
        captions_url = en_captions_url,
        video_id=video_id
    )

def process_channel_vods(flat_playlist_vods):
    """
    Takes the output of Pass 1 and threads the remaining checks.
    """
    final_valid_vods = []
    # max_workers=5 keeps us fast without getting rate-limited by YouTube
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(validate_single_vod, x) for x in flat_playlist_vods]

        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                 final_valid_vods.append({
                    'title': result.title,
                    'url': result.url,
                    'date': result.date,
                    'creator': result.creator,
                    'captions_url': result.captions_url,
                    'video_id': result.video_id
                 })
    logger.info(f"Returning {len(final_valid_vods)} VODs");               
    return final_valid_vods

def _build_channel_url(channel_input: str) -> str:
    clean_input = channel_input.strip()
    if not clean_input.startswith("http"):
        if not clean_input.startswith("@"):
            clean_input = f"@{clean_input}"
        url = f"https://www.youtube.com/{clean_input}/streams"
    else:
        url = clean_input if "/streams" in clean_input else f"{clean_input}/streams"
    return url

def _fetch_playlist_data(url: str, date_after, date_before=None) -> list:
    cmd = ['yt-dlp', '--dump-json', '--no-download', '--ignore-no-formats-error']

    if date_after:
        date_str = date_after.strftime('%Y%m%d')
        cmd.extend(['--dateafter', date_str])
        
    if date_before:
        date_before_str = date_before.strftime('%Y%m%d')
        cmd.extend(['--datebefore', date_before_str])

    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=300)
    except subprocess.TimeoutExpired:
        logger.error(f"yt-dlp scan timed out after 300 seconds for {url}")
        raise RuntimeError("The YouTube channel scan timed out after 5 minutes. YouTube may be throttling the connection or the channel archive is massive. Please try again.")
    
    if result.returncode != 0:
        logger.error(f"yt-dlp failure: {result.stderr}")
        raise RuntimeError(f"yt-dlp Live Stream scanning operation failure: {result.stderr}")

    playlist_data = []
    for line in result.stdout.strip().split('\n'):
        if line:
            playlist_data.append(json.loads(line))
    return playlist_data

from datetime import timedelta

def fetch_vod_playlist(channel_input: str, date_after=None, limit: int = 50) -> list:
    logger.info(f"Fetching VODs from Channel {channel_input} with limit of {limit} days");
    url = _build_channel_url(channel_input)

    if not date_after:
        date_after = dt_date.today() - timedelta(days=limit)

    current_end_date = dt_date.today()

    chunks = []
    current_start = date_after
    while current_start <= current_end_date:
        chunk_end = current_start + timedelta(days=6)
        if chunk_end > current_end_date:
            chunk_end = current_end_date
        chunks.append((current_start, chunk_end))
        current_start = chunk_end + timedelta(days=1)

    vod_playlist = []

    # max_workers=5 keeps us fast without getting rate-limited by YouTube
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_fetch_playlist_data, url, start, end) for start, end in chunks]

        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    vod_playlist.extend(result)
            except Exception as e:
                logger.error(f"Error fetching playlist chunk: {e}")

    return vod_playlist
