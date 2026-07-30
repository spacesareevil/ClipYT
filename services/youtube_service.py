import re
import logging
import yt_dlp
import concurrent.futures
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from datetime import datetime, date as dt_date
from concurrent.futures import as_completed
from urllib.parse import urlparse
from services.channel_cache_service import is_playlist_cache_stale, load_channel_playlist_cache, save_channel_playlist_cache, save_channel_vod_cache

logger = logging.getLogger(__name__)

@dataclass
class VodData:
    title: str
    url: str
    timestamp: int
    date: dt_date
    duration: str
    video_id: str
    creator: str
    captions_url: str
    height: int
    width: int

#Get ID of Video from URL
def extract_youtube_id(url: str) -> str:
    pattern = r'(?:v=|\/shorts\/|\/embed\/|\/v\/|youtu\.be\/|\/watch\?v=|\/live\/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

#Private helper to get video details from YT-DLP for more metadata
def _get_vod_details(vod_url):

    vod_opts = {
        'simulate': True,            # Do not download the video file
        'ignoreerrors': True,
        'writesubtitles': True,      # Tells yt-dlp to look for and map subtitles
        'writeautomaticsub': True,   # Includes YouTube's auto-generated captions
    } 

    try:
        with yt_dlp.YoutubeDL(vod_opts) as ydl:
            vod_data = ydl.extract_info(vod_url, download=False)
    except Exception as e:
        raise RuntimeError("An error occurred while retrieving individual VOD information: {e}")
    
    return vod_data   

def _is_timestamp_inside_days_back(video_timestamp: int, days_back: int) -> bool:
    start_date = (datetime.now() - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_date_str = start_date.strftime('%Y%m%d')
    start_timestamp = datetime.strptime(start_date_str, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()

    end_date = datetime.combine(dt_date.today(), datetime.min.time())
    end_date_str = end_date.strftime('%Y%m%d')
    end_timestamp = datetime.strptime(end_date_str, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()

    if video_timestamp is not None and start_timestamp <= video_timestamp <= end_timestamp:
        return True
    else:
        return False

#Vertical VOD Validation
def single_vod_is_vertical_and_valid(vod, days_back):
    vod_url = vod.url
    vod_details = _get_vod_details(vod_url)

    

    vod_timestamp = vod_details['timestamp']

    if vod_timestamp != vod.timestamp:
        logger.info(f"Timestamp Mismatch for {vod.video_id}-{vod.title[0:20]}: Using new timestamp for more accurate filtering")
        #Another date check, last one used approximate timestamps. This uses definitive timestamps
        vod.timestamp = vod_timestamp
        if not _is_timestamp_inside_days_back(vod_timestamp, days_back):
            logger.info(f"CHECK FAILED ON {vod.video_id}-{vod.title[0:20]}: VOD timestamp is outside of lookback period")
            return None

    raw_date = vod_details.get('upload_date', '')
    formatted_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}" if raw_date and len(raw_date) == 8 else datetime.today().strftime('%Y-%m-%d')

    vod.date = formatted_date
    vod.height = vod_details['height']
    vod.width = vod_details['width']
    vod.creator = vod_details['uploader']
    vod.duration = vod_details['duration']
    live_status = vod_details['live_status']

    
    if live_status == "is_upcoming":    #Ignore Scheduled Streams
        logger.info(f"CHECK FAILED ON {vod.video_id}-{vod.title[0:20]}: VOD is scheduled")
        return None
    
    if live_status == "post_live":      #Ignore lives that youtube has yet to process
        logger.info(f"CHECK FAILED ON {vod.video_id}-{vod.title[0:20]}: VOD processing")
        return None

    if vod.height < vod.width:                  #Ignore Horizontal Format (maybe make a toggle for horizontal/vertical?)
        logger.info(f"CHECK FAILED ON {vod.video_id}-{vod.title[0:20]}: Horizontal VOD")
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
        logger.info(f"CHECK FAILED ON {vod.video_id}-{vod.title[0:20]}: No English VTT captions found")
        return None

    vod.captions_url = en_captions_url

    logger.info(f"CHECK PASSED ON {vod.video_id}-{vod.title[0:20]}")
    return {
        'title':vod.title,
        'url':vod.url,
        'timestamp':vod.timestamp,
        'date':vod.date,
        'duration':vod.duration,
        'video_id':vod.video_id,
        'creator':vod.creator,
        'captions_url':vod.captions_url,
        'height':vod.height,
        'width':vod.width
    }

#Threaded method to iterate playlist to filter for valid vertical vods
def find_vertical_valid_vods(channel, flat_playlist_vods, days_back):
    """
    Takes the output of Pass 1 and threads the remaining checks.
    """
    final_valid_vods = []
    # max_workers=5 keeps us fast without getting rate-limited by YouTube
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(single_vod_is_vertical_and_valid, x, days_back) for x in flat_playlist_vods]

        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                 final_valid_vods.append(result)

    logger.info(f"Returning {len(final_valid_vods)} VODs");  
    #Cache Final VODs
    save_channel_vod_cache(channel, final_valid_vods)            
    return final_valid_vods

#Initial YT-DLP scrape of playlist information
def _fetch_playlist_data(url: str) -> list:
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

            #Convert Dict to list
            if playlist_dict and 'entries' in playlist_dict:
                for entry in playlist_dict['entries']:
                    playlist_data.append(entry)                        
    except Exception as e:
        logger.error(f"An error occurred while scanning: {e}")
        raise RuntimeError("An error occurred while scanning: {e}")

    return playlist_data

#Private helper to return a proper URL for a given channel
def _build_channel_url(channel_input: str) -> str:
    clean_input = channel_input.strip()
    if not clean_input.startswith("http"):
        if not clean_input.startswith("@"):
            clean_input = f"@{clean_input}"
        url = f"https://www.youtube.com/{clean_input}/streams"
    else:
        url = clean_input if "/streams" in clean_input else f"{clean_input}/streams"
    return url

def _get_voddata(vod):
    return VodData(
        title=vod['title'],
        url=vod['url'],
        timestamp=vod['timestamp'],
        date=datetime.fromtimestamp(vod['timestamp']),
        duration=vod['duration'],
        video_id=vod['id'],
        creator='',
        captions_url='',
        height=0,
        width=0
    )

# Called from main_window.py to Find VODs for channel
def fetch_vod_playlist(channel_input: str, days_back=30, force_refresh_cache=False) -> list:
    logger.info(f"Fetching VODs from Channel {channel_input} going {days_back} days back. Force Cache Refresh = {force_refresh_cache}");
    url = _build_channel_url(channel_input)
    playlist_vods = []

    try:
        stale = is_playlist_cache_stale(channel_input)

        if stale or force_refresh_cache:
            logger.info(f"Fetching VODs from YouTube via yt-dlp")
            playlist_vods = _fetch_playlist_data(url)
            #Save Cache
            logger.info(f"Saving playlist to cache")
            save_channel_playlist_cache(channel_input, playlist_vods)
        else:
            logger.info(f"Cache is fresh, loading from local file")
            playlist_vods = load_channel_playlist_cache(channel_input)
            
    except Exception as e:
            logger.error(f"Error fetching playlist vods: {e}")

    logger.info(f"Filtering VODs going {days_back} days back from playlist")

    start_date = (datetime.now() - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_date_str = start_date.strftime('%Y%m%d')
    start_timestamp = datetime.strptime(start_date_str, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()

    end_date = datetime.combine(dt_date.today(), datetime.min.time())
    end_date_str = end_date.strftime('%Y%m%d')
    end_timestamp = datetime.strptime(end_date_str, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()

    vods_in_range = []
    try:
        for vod in playlist_vods:
            video_timestamp = vod.get('timestamp')
            if video_timestamp is not None and start_timestamp <= video_timestamp <= end_timestamp:
                vods_in_range.append(_get_voddata(vod))
    except Exception as e:
        logger.error(f"Error fetching playlist chunk: {e}")

    logger.info(f"Found {len(vods_in_range)} in the past {days_back} days from channel playlist. Timestamps are estimates and some VODs may be returned outside of the target timeline. Filtered again later")
    return vods_in_range

#Private helper method to extract channel name from URL
def _get_channel_name_from_url(channel_url: str) -> str:
    return channel_url.split('@')[-1].split('/')[0]