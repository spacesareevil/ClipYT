import re

def clean_filename(text: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(text)).strip()

def build_clip_filename(row: dict, active_sheet_title: str) -> str:
    title_val = str(row.get("Title", "Untitled Clip")).strip()
    viral_val = str(row.get("Viral Score", "0%")).strip()
    live_title_val = str(row.get("Live Title", active_sheet_title)).strip()
    
    clean_title = clean_filename(title_val)
    clean_viral = clean_filename(viral_val.replace("%", ""))
    clean_live = clean_filename(live_title_val)
    
    return f"{clean_title}_{clean_viral}_{clean_live}.mp4"