import os
import json
import logging
import time
from config.settings import config

logger = logging.getLogger(__name__)

def sanitize_channel_name(channel_name: str) -> str:
    """Sanitize the channel name for use as a filename."""
    return "".join(c for c in channel_name if c.isalnum() or c in ('_', '-')).strip()

def get_playlist_cache_path(channel_name: str) -> str:
    safe_name = sanitize_channel_name(channel_name)
    return os.path.join(f"{config.channel_cache_dir}", f"{safe_name}_Playlist_Cache.json")

def get_vod_cache_path(channel_name: str) -> str:
    safe_name = sanitize_channel_name(channel_name)
    return os.path.join(f"{config.channel_cache_dir}", f"{safe_name}_VOD_Cache.json")

def get_final_vod_cache_path(channel_name: str) -> str:
    safe_name = sanitize_channel_name(channel_name)
    return os.path.join(f"{config.channel_cache_dir}", f"{safe_name}_Final_VOD_Cache.json")

def is_playlist_cache_stale(channel_name: str) -> bool:
    """Checks if the cache file for a channel is older than 24 hours."""
    cache_path = get_playlist_cache_path(channel_name)
    if not os.path.exists(cache_path):
        return True
    
    if os.path.getsize(cache_path) <= 2:
        return True

    file_mtime = os.path.getmtime(cache_path)
    current_time = time.time()
    # 24 hours in seconds = 86400
    if (current_time - file_mtime) > 86400:
        return True

    return False

def load_channel_playlist_cache(channel_name: str) -> list:
    """Loads cached Playlists for a given channel."""
    cache_path = get_playlist_cache_path(channel_name)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load channel playlist cache for {channel_name}: {e}")
    return []

def load_channel_vod_cache(channel_name: str) -> list:
    """Loads cached Playlists for a given channel."""
    cache_path = get_vod_cache_path(channel_name)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load channel playlist cache for {channel_name}: {e}")
    return []

def save_channel_playlist_cache(channel_name: str, vods: list):
    """Saves Playlist cache for a given channel."""
    cache_path = get_playlist_cache_path(channel_name)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(vods, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save channel playlist cache for {channel_name}: {e}")

def save_channel_vod_cache(channel_name: str, vods: list):
    """Saves VOD cache for a given channel."""
    cache_path = get_vod_cache_path(channel_name)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(vods, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save channel VOD cache for {channel_name}: {e}")

def load_valid_vod_cache(channel_name: str) -> list:
    """Loads cached VODs for a given channel."""
    cache_path = get_final_vod_cache_path(channel_name)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load channel final VOD cache for {channel_name}: {e}")
    return []

def save_valid_vod_cache(channel_name: str, vods: list):
    """Saves VODs cache for a given channel."""
    cache_path = get_final_vod_cache_path(channel_name)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(vods, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save channel final VOD cache for {channel_name}: {e}")

def load_last_channel() -> str:
    """Loads the last scanned channel from cache."""
    if os.path.exists(config.last_channel_cache_file):
        try:
            with open(config.last_channel_cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("last_channel", "")
        except Exception as e:
            logger.error(f"Failed to load last channel cache: {e}")
    return ""

def save_last_channel(channel_name: str):
    """Saves the last scanned channel to cache."""
    try:
        with open(config.last_channel_cache_file, "w", encoding="utf-8") as f:
            json.dump({"last_channel": channel_name}, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save last channel cache: {e}")
