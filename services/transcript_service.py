import os
import re
import json
import logging
import difflib
import yt_dlp
import requests
import io
import webvtt
from config.settings import config

logger = logging.getLogger(__name__)

class TranscriptService:
    def __init__(self):
        self.cache_dir = config.cache_dir

    def _get_cached_transcript(self, video_id: str):
        cache_path = os.path.join(self.cache_dir, f"{video_id}.json")
        if os.path.exists(cache_path):
            logger.info(f"Loaded transcript from local disk cache for Video ID: {video_id}")
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def _save_to_cache(self, video_id: str, data: list):
        cache_path = os.path.join(self.cache_dir, f"{video_id}.json")
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _clean_text(self, text: str) -> str:
        text = text.replace('\n', ' ').strip()
        text = re.sub(r'<[^>]*>', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text

    def _deduplicate_rolling_text(self, text1: str, text2: str) -> str:
        # Split texts into words
        words1 = text1.split()
        words2 = text2.split()

        # If either is empty, return the other
        if not words1:
            return text2
        if not words2:
            return ""

        matcher = difflib.SequenceMatcher(None, words1, words2)
        match = matcher.find_longest_match(0, len(words1), 0, len(words2))

        if match.size > 0 and match.b == 0 and match.a + match.size == len(words1):
            return " ".join(words2[match.size:])

        # Also try exact prefix match if fuzzy fails
        if text2.startswith(text1):
            return text2[len(text1):].strip()

        return text2

    def _filter_by_speech_density(self, transcript_list: list, chunk_sec: int = 300, min_words: int = 50) -> list:
        if not transcript_list: 
            return []

        chunks = {}
        for entry in transcript_list:
            start = int(getattr(entry, 'start', entry.get('start', 0)))
            bucket_idx = start // chunk_sec
            if bucket_idx not in chunks:
                chunks[bucket_idx] = []
            chunks[bucket_idx].append(entry)

        filtered_list = []
        dropped_chunks = 0
        
        for bucket_idx in sorted(chunks.keys()):
            bucket = chunks[bucket_idx]
            text_block = " ".join([getattr(e, 'text', e.get('text', '')) for e in bucket])
            word_count = len(text_block.split())

            if word_count >= min_words:
                filtered_list.extend(bucket)
            else:
                dropped_chunks += 1
                
        if dropped_chunks > 0:
            logger.info(f"Density Filter dropped {dropped_chunks} low-activity chunk(s) (~{dropped_chunks * chunk_sec / 60} mins of dead air).")

        return filtered_list

    def get_formatted_transcript(self, video_id: str, captions_url: str) -> str:
        logger.info(f"Initiating transcript extraction for Video ID: {video_id}")
        
        transcript_data = self._get_cached_transcript(video_id)
        
        if not transcript_data:
            if not captions_url:
                logger.error(f"Transcript extraction failed for Video ID: {video_id}. Error: captions_url not provided")
                raise RuntimeError(f"Could not locate automated subtitles for video ID {video_id}. Details: captions_url not provided")
            try:
                logger.info(f"Downloading transcript via VTT URL with Video ID: {video_id}")

                # Fetch the VTT file content directly into memory
                response = requests.get(captions_url)
                vtt_text = response.text

                # Parse the raw text string using webvtt and StringIO
                captions = webvtt.read_buffer(io.StringIO(vtt_text))
                
                # Structure the data and deduplicate rolling text
                transcript_data = []
                previous_text = ""
                for caption in captions:
                    clean_text = self._clean_text(caption.text)
                    deduped_text = self._deduplicate_rolling_text(previous_text, clean_text)
                    if deduped_text:
                        transcript_data.append({
                            'start': caption.start_in_seconds,
                            'end': caption.end_in_seconds,
                            'text': deduped_text
                        })
                    previous_text = clean_text

                self._save_to_cache(video_id, transcript_data)
            except Exception as e:
                logger.error(f"Transcript extraction failed for Video ID: {video_id}. Error: {str(e)}")
                raise RuntimeError(f"Could not locate automated subtitles for video ID {video_id}. Details: {str(e)}")

        dense_transcript = self._filter_by_speech_density(transcript_data)

        formatted_lines = []
        for entry in dense_transcript:
            start_seconds = int(getattr(entry, 'start', entry.get('start', 0)))
            raw_text = getattr(entry, 'text', entry.get('text', ''))
            
            clean_txt = self._clean_text(raw_text)
            
            if not clean_txt or clean_txt.startswith('[Music]') or clean_txt.startswith('[Applause]'):
                continue 
            
            hours = start_seconds // 3600
            minutes = (start_seconds % 3600) // 60
            seconds = start_seconds % 60
            timestamp = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            formatted_lines.append(f"{timestamp} {clean_txt}")
            
        logger.info(f"Successfully formatted & cleaned transcript ({len(formatted_lines)} lines) for Video ID: {video_id}")
        return "\n".join(formatted_lines)

_transcript_service = TranscriptService()

def get_formatted_transcript(video_id: str, caption_url: str) -> str:
    return _transcript_service.get_formatted_transcript(video_id, caption_url)