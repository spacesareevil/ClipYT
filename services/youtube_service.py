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
from youtube_transcript_api import YouTubeTranscriptApi
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
    
    automatic_captions = vod['automatic_captions'] 

    if automatic_captions is None:      #Ignore videos that do not have automatic captions
        logger.info(f"CHECK FAILED ON {video_id}-{title[0:20]}: No captions found, uploader should check VOD copyright issues")
        return None
    
    if "en" in automatic_captions:
        en_automatic_captions = automatic_captions["en"][0]
        if en_automatic_captions["name"] == "English":
            en_captions_url = en_automatic_captions["url"]

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

def _fetch_playlist_data(url: str, date_after, limit: int) -> list:
    cmd = ['yt-dlp', '--dump-json', '--no-download', '--ignore-no-formats-error']
    
    # Apply the limit unless the user passed 0 (which means fetch all)
    if limit > 0:
        cmd.extend(['--playlist-end', str(limit)])

    if date_after:
        date_str = date_after.strftime('%Y%m%d')
        cmd.extend(['--dateafter', date_str])
        
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

def fetch_vod_playlist(channel_input: str, date_after=None, limit: int = 50) -> list:
    logger.info(f"Fetching {limit} VODs from Channel {channel_input}");
    url = _build_channel_url(channel_input)
    vod_playlist = _fetch_playlist_data(url, date_after, limit)
    return vod_playlist
