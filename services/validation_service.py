import os
import json
import logging
import hashlib
import time
from datetime import datetime, timedelta
from config.settings import config
from models.clip_models import ClipReviewResult
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Constants
CACHE_FILE = "gemini_file_cache.json"
CACHE_RETENTION_DAYS = 90

def _get_cache_path():
    return os.path.join(config.gemini_cache_dir, CACHE_FILE)

def _load_cache():
    cache_path = _get_cache_path()
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[VALIDATION CACHE] Error loading cache: {e}")
    return {}

def _save_cache(cache_data):
    cache_path = _get_cache_path()
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"[VALIDATION CACHE] Error saving cache: {e}")

def _generate_cache_key(local_vod_path, start, end):
    raw_key = f"{local_vod_path}_{start}_{end}"
    return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()

def purge_expired_cache(ai_client):
    """Purges cached Gemini File API objects older than the retention period."""
    cache = _load_cache()
    keys_to_remove = []
    now = datetime.now()

    for key, data in cache.items():
        cached_time_str = data.get("timestamp")
        file_name = data.get("file_name")
        if not cached_time_str or not file_name:
            keys_to_remove.append(key)
            continue

        try:
            cached_time = datetime.fromisoformat(cached_time_str)
            if now - cached_time > timedelta(days=CACHE_RETENTION_DAYS):
                logger.info(f"[VALIDATION CACHE] Purging expired remote file from Gemini servers: {file_name}")
                try:
                    ai_client.files.delete(name=file_name)
                except Exception as e:
                    logger.warning(f"[VALIDATION CACHE] Could not delete remote file {file_name}: {e}")
                keys_to_remove.append(key)
        except ValueError:
            keys_to_remove.append(key)

    for key in keys_to_remove:
        del cache[key]

    if keys_to_remove:
        _save_cache(cache)
        logger.info(f"[VALIDATION CACHE] Purged {len(keys_to_remove)} expired entries.")

def delete_cached_file(ai_client, local_vod_path, start, end):
    """Programmatically deletes the associated Gemini File API object once final validated timestamps are successfully handled."""
    cache_key = _generate_cache_key(local_vod_path, start, end)
    cache = _load_cache()

    if cache_key in cache:
        file_name = cache[cache_key].get("file_name")
        if file_name:
            logger.info(f"[VALIDATION CACHE] Deleting remote file from Gemini servers as validation is complete: {file_name}")
            try:
                ai_client.files.delete(name=file_name)
            except Exception as e:
                logger.warning(f"[VALIDATION CACHE] Could not delete remote file {file_name}: {e}")

        del cache[cache_key]
        _save_cache(cache)

def agentic_clip_review(ai_client, local_staging_path, local_vod_path, row, max_retries=3):
    """
    Uploads (or retrieves from cache) the locally cached video chunk to the Gemini File API.
    Constructs a prompt instructing Gemini to review both video frames and audio to verify if on-screen action aligns with dialogue.
    Requests precise, tight start and end timestamps.
    Includes a retry loop and fails-closed if validation continuously errors out.
    """
    title = row.get("Title", "")
    desc = row.get("Description", "")
    notes = row.get("Editing Notes", "")
    start = str(row.get("Timestamp Start", ""))
    end = str(row.get("Timestamp End", ""))

    cache_key = _generate_cache_key(local_vod_path, start, end)

    for attempt in range(max_retries):
        try:
            cache = _load_cache()
            video_file = None

            # Check cache first
            if cache_key in cache:
                file_name = cache[cache_key].get("file_name")
                logger.info(f"[QA REVIEW] Found cached Gemini file: {file_name} for segment {start}-{end}")
                try:
                    video_file = ai_client.files.get(name=file_name)
                except Exception as e:
                    logger.warning(f"[QA REVIEW] Cached file {file_name} not found on server, will re-upload: {e}")
                    video_file = None

            # Upload if not cached or cache invalid
            if not video_file:
                logger.info(f"[QA REVIEW] Uploading {local_staging_path} to Gemini for visual analysis (Attempt {attempt+1}/{max_retries})...")
                video_file = ai_client.files.upload(file=local_staging_path)

                # Save to cache
                cache[cache_key] = {
                    "file_name": video_file.name,
                    "timestamp": datetime.now().isoformat()
                }
                _save_cache(cache)

            # Poll Google until the video is fully processed and ready for analysis
            while not video_file.state or video_file.state.name != "ACTIVE":
                if video_file.state and video_file.state.name == "FAILED":
                    # Fix cache poisoning: delete from cache and remove remote file if failed
                    logger.error(f"[QA REVIEW] Gemini failed to process video {video_file.name}. Purging from cache.")
                    try:
                        ai_client.files.delete(name=video_file.name)
                    except Exception:
                        pass
                    if cache_key in cache:
                        del cache[cache_key]
                        _save_cache(cache)
                    raise RuntimeError("Gemini failed to process the video file.")
                time.sleep(3)
                video_file = ai_client.files.get(name=video_file.name)

            system_instruction = (
                "You are an expert video Quality Assurance reviewer. Watch the provided video clip and listen to its audio track. "
                "Compare its actual visual and audio content against the expected metadata and intended viral moment. "
                "Verify if the on-screen action (gameplay intensity, visual reactions, facecam cues) aligns with the dialogue hype. "
                "Determine if the clip correctly captures the intended subject matter. "
                "If the current clip length is poorly timed, provide precise, tight start and end timestamps "
                "(e.g., trimming down to a pristine viral clip) based on these multimodal cues to fix it. Timestamps must be in HH:MM:SS or MM:SS format relative to the original video."
            )

            user_prompt = (
                f"Expected Title: {title}\n"
                f"Expected Description: {desc}\n"
                f"Editing Notes / Intended Moment: {notes}\n"
                f"Current Clip Original Timestamps: Start={start}, End={end}\n\n"
                "Review the attached video chunk and audio track. Does it accurately reflect this metadata and capture the best frames? Describe what actually happens visually. "
                "If the clip needs better timing to capture the absolute best frames, return new precise start and end timestamps in new_start_time and new_end_time fields."
            )

            logger.info("[QA REVIEW] Video active. Requesting agentic review from Gemini...")
            response = ai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[video_file, user_prompt],
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=ClipReviewResult,
                    temperature=0.2
                )
            )

            review_data = json.loads(response.text)
            logger.info(f"[QA REVIEW] Complete. Match: {review_data.get('is_match')}, Grade: {review_data.get('grade')}")
            if review_data.get('new_start_time') and review_data.get('new_end_time'):
                logger.info(f"[QA REVIEW] New suggested timestamps: {review_data.get('new_start_time')} - {review_data.get('new_end_time')}")
            return review_data

        except Exception as e:
            logger.error(f"[QA REVIEW ERROR] Attempt {attempt+1} failed: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                # Fails closed
                raise RuntimeError(f"Agentic QA review failed after {max_retries} attempts: {str(e)}")
