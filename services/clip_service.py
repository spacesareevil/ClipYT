import logging
import subprocess
from utils.timestamps import timestamp_to_seconds

logger = logging.getLogger(__name__)

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