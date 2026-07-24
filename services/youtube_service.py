import re
import logging
import yt_dlp
import concurrent.futures
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from datetime import datetime, date as dt_date
from concurrent.futures import as_completed
from urllib.parse import urlparse
from services.channel_cache_service import save_channel_cache

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
    vod_details = _get_vod_details(vod)

    live_status = vod_details['live_status']
    video_id = vod_details['id']
    title= vod_details['title']    
    
    if live_status == "is_upcoming":    #Ignore Scheduled Streams
        logger.info(f"CHECK FAILED ON {video_id}-{title[0:20]}: VOD is scheduled")
        return None
    
    if live_status == "post_live":      #Ignore lives that youtube has yet to process
        logger.info(f"CHECK FAILED ON {video_id}-{title[0:20]}: VOD processing")
        return None
        
    height = vod_details['height']
    width = vod_details['width']

    if height < width:                  #Ignore Horizontal Format (maybe make a toggle for horizontal/vertical?)
        logger.info(f"CHECK FAILED ON {video_id}-{title[0:20]}: Horizontal VOD")
        return None
    
    automatic_captions = vod_details.get('automatic_captions')
    subtitles = vod_details.get('subtitles')

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

    raw_date = vod_details.get('upload_date', '')
    formatted_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}" if raw_date and len(raw_date) == 8 else datetime.today().strftime('%Y-%m-%d')
    logger.info(f"CHECK PASSED ON {video_id}-{title[0:20]}")
    return VerticalVodData(
        title = title,
        url = vod_details['webpage_url'],
        date = formatted_date,
        creator = vod_details['uploader'],
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

def _get_vod_details(vod):

    vod_opts = {
        'simulate': True,            # Do not download the video file
        'ignoreerrors': True,
        'writesubtitles': True,      # Tells yt-dlp to look for and map subtitles
        'writeautomaticsub': True,   # Includes YouTube's auto-generated captions
    } 

    vod_url = vod['url']

    try:
        with yt_dlp.YoutubeDL(vod_opts) as ydl:
            vod_data = ydl.extract_info(vod_url, download=False)
    except Exception as e:
        raise RuntimeError("An error occurred while retrieving individual VOD information: {e}")
    
    return vod_data           

def _build_channel_url(channel_input: str) -> str:
    clean_input = channel_input.strip()
    if not clean_input.startswith("http"):
        if not clean_input.startswith("@"):
            clean_input = f"@{clean_input}"
        url = f"https://www.youtube.com/{clean_input}/streams"
    else:
        url = clean_input if "/streams" in clean_input else f"{clean_input}/streams"
    return url

def _get_channel_name_from_url(channel_url: str) -> str:
    return channel_url.split('@')[-1].split('/')[0]

def _fetch_playlist_data(url: str, start_date, end_date=datetime.today) -> list:
    if start_date:
        start_date_str = start_date.strftime('%Y%m%d')
        start_timestamp = datetime.strptime(start_date_str, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()
        
    if end_date:
        end_date_str = end_date.strftime('%Y%m%d')
        end_timestamp = datetime.strptime(end_date_str, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()
    
    ydl_opts = {
        'simulate': True, # Equivalent to --no-download
        'ignoreerrors': 'only_download', # Equivalent to --ignore-no-formats-error
        'extract_flat': 'in_playlist',
        'extractor_args': {
            'youtubetab': {
                'approximate_date': ['true']
            }
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # This returns the data directly as a Python dictionary
            playlist_dict = ydl.extract_info(url, download=False)
            playlist_data = []

            if playlist_dict and 'entries' in playlist_dict:
                for entry in playlist_dict['entries']:
                    video_timestamp = entry.get('timestamp')
                    if video_timestamp is not None and start_timestamp <= video_timestamp <= end_timestamp:
                        playlist_data.append(entry)
    except Exception as e:
        logger.error(f"An error occurred while scanning: {e}")
        raise RuntimeError("An error occurred while scanning: {e}")

    # CACHE PLAYLIST_DATA
    channel_name = _get_channel_name_from_url(url)
    save_channel_cache(channel_name, playlist_data)
    return playlist_data

def fetch_vod_playlist(channel_input: str, days_back=30) -> list:
    logger.info(f"Fetching VODs from Channel {channel_input} going {days_back} days back");
    url = _build_channel_url(channel_input)

    end_date = datetime.combine(dt_date.today(), datetime.min.time())
    start_date = (datetime.now() - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)

    
    try:
        vod_playlist = _fetch_playlist_data(url, start_date, end_date)
    except Exception as e:
        logger.error(f"Error fetching playlist chunk: {e}")

    return vod_playlist
