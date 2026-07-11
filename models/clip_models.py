from pydantic import BaseModel

class ClipRow(BaseModel):
    live_title: str
    timestamp_start: str
    timestamp_end: str
    clip_length_sec: int
    viral_score: str
    on_screen_hook: str
    title: str
    description: str
    hashtags: str
    editing_notes: str

class IngestionAnalysisResult(BaseModel):
    clips: list[ClipRow]

class ClipReviewResult(BaseModel):
    grade: str
    visual_description: str
    is_match: bool
    feedback: str
    new_start_time: str | None = None
    new_end_time: str | None = None