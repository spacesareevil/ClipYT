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

def check_captions_exist(video_id: str) -> bool:
    """
    Directly queries the YouTube Innertube API to check for closed captions.
    This bypasses downloading the full HTML webpage, resulting in ~5x faster execution.
    """
    url = "https://www.youtube.com/youtubei/v1/player"
    payload = json.dumps({
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": "2.20230301.00.00" # Standard web client version payload
            }
        },
        "videoId": video_id
    }).encode('utf-8')

    req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res_json = json.loads(response.read())
            # The captions object only exists if CC/Transcripts are available
            captions = res_json.get("captions", {})

            if captions and "playerCaptionsTracklistRenderer" in captions:
                return True
    except Exception as e:
        logger.warning(f"Innertube API check failed for {video_id}: {str(e)}")
        
    return False

def fetch_latest_channel_vods(channel_input: str, date_after=None, limit: int = 50) -> list:
    clean_input = channel_input.strip()
    if not clean_input.startswith("http"):
        if not clean_input.startswith("@"):
            clean_input = f"@{clean_input}"
        url = f"https://www.youtube.com/{clean_input}/streams"
    else:
        url = clean_input if "/streams" in clean_input else f"{clean_input}/streams"
    
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

    vods = []
    vod_count = len(result.stdout.strip().split('\n'))
    logger.debug(f"Found {vod_count} VODs. Filtering for Vertical VODs only")
    for line in result.stdout.strip().split('\n'):
        if line:
            data = json.loads(line)     
            yt_url = data.get('url')

            format_cmd = ['yt-dlp', '--quiet', '--format', 'bv*[ext=mp4]','--print', '%(resolution)s', f"{yt_url}"]
            try:
                format_result = subprocess.run(format_cmd, capture_output=True, text=True, check=True)
                resolution = format_result.stdout.strip();
                if result.returncode != 0:
                    logger.error(f"yt-dlp failure: {result.stderr}")
                    raise RuntimeError(f"yt-dlp Live Stream scanning operation failure: {result.stderr}")

            except subprocess.TimeoutExpired:
                logger.error(f"yt-dlp scan timed out after 300 seconds for {url}")
                raise RuntimeError("The YouTube channel scan timed out after 5 minutes. YouTube may be throttling the connection or the channel archive is massive. Please try again.")
    
            width = resolution.split("x", 1)[0]
            height = resolution.partition("x")[2]

            # Check for vertical aspect ratio
            if width and height and height > width:
                video_id = data.get('id')
                video_title = data.get('title')
                logger.debug(f"Video {video_title} is vertical format at {resolution}")
                
                # Verify that the vertical video actually has a transcript available
                if video_id and check_captions_exist(video_id):
                    raw_date = data.get('upload_date', '')
                    formatted_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}" if len(raw_date) == 8 else datetime.today().strftime('%Y-%m-%d')
                    
                    vods.append({
                        'title': data.get('title', 'Unknown Title'),
                        'url': f"https://www.youtube.com/watch?v={video_id}",
                        'date': formatted_date,
                        'creator': data.get('uploader', 'Unknown Creator')
                    })
                else:
                    logger.debug(f"Skipping VOD {video_id} - No captions available.")
            
    vods.sort(key=lambda x: x['date'], reverse=True)
    logger.debug(f"Successfully scraped {len(vods)} valid VODs from {clean_input}")
    return vods