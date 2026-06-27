import re
import json
import logging
import subprocess
import urllib.request
import yt_dlp
import concurrent.futures
from datetime import datetime

logger = logging.getLogger(__name__)

def extract_youtube_id(url: str) -> str:
    pattern = r'(?:v=|\/shorts\/|\/embed\/|\/v\/|youtu\.be\/|\/watch\?v=|\/live\/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def validate_single_vod(vod):
    """
    Worker function that executes Pass 2 and Pass 3 locally.
    Returns the VOD if it passes both, otherwise returns None.
    """
    url = vod['url'] # Adjust this based on how your Pass 1 dictionaries are structured
    
    # 1. Native Python yt-dlp check (No subprocess overhead!)
    ydl_opts = {
        'quiet': True,
        'simulate': True,
        'no_warnings': True,
        'extract_flat': False # We need the actual video metadata
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # download=False means we are ONLY pulling metadata
            info = ydl.extract_info(url, download=False)
            
            # Safely grab dimensions (defaulting to horizontal if missing)
            width = info.get('width', 1920)
            height = info.get('height', 1080)
            
            # PASS 2: Is it vertical?
            if width >= height:
                return None  # Discard immediately, not vertical
                
            # PASS 3: If it IS vertical, check captions immediately using info directly
            has_captions = bool(info.get('subtitles')) or bool(info.get('automatic_captions'))
            if not has_captions:
                return None # Discard, no captions

        video_id = vod.get('id') or extract_youtube_id(url)
        if not video_id:
            return None
            
        raw_date = vod.get('upload_date', '')
        formatted_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}" if raw_date and len(raw_date) == 8 else datetime.today().strftime('%Y-%m-%d')

        return {
            'title': vod.get('title', 'Unknown Title'),
            'url': f"https://www.youtube.com/watch?v={video_id}",
            'date': formatted_date,
            'creator': vod.get('uploader', 'Unknown Creator')
        }
        
    except Exception as e:
        print(f"Error analyzing metadata for {url}: {e}")
        return None

def process_channel_vods(flat_playlist_vods):
    """
    Takes the output of Pass 1 and threads the remaining checks.
    """
    final_valid_vods = []
    
    # max_workers=5 keeps us fast without getting rate-limited by YouTube
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # executor.map handles feeding the list to the worker function across threads
        results = executor.map(validate_single_vod, flat_playlist_vods)
        
        for result in results:
            if result is not None:
                final_valid_vods.append(result)
                
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
    cmd = ['yt-dlp', '--flat-playlist', '--dump-json', '--no-download']
    
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

def fetch_latest_channel_vods(channel_input: str, date_after=None, limit: int = 50) -> list:
    url = _build_channel_url(channel_input)
    playlist_data = _fetch_playlist_data(url, date_after, limit)

    vods = process_channel_vods(playlist_data)
            
    vods.sort(key=lambda x: x['date'], reverse=True)
    logger.debug(f"Successfully scraped {len(vods)} valid VODs from {channel_input}")
    return vods