import os
import sys
import logging
from dataclasses import dataclass, field

@dataclass
class Settings:
    # Google OAuth Paths
    client_secrets_file: str = field(default_factory=lambda: os.getenv("YT_CLIENT_SECRETS", "client_secrets.json"))
    token_cache_file: str = field(default_factory=lambda: os.getenv("YT_TOKEN_CACHE", "token.json"))
    layout_cache_file: str = "layout_config.json"
    
    # API Keys
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY"))

    # Google Workspace Targets
    spreadsheet_name: str = "YouTube Live Stream Clips"
    master_drive_folder_id: str = "1G9UwjtRUlkdFbiYY1x-i7qStoc4vSFKy"

    # Local Directory Paths
    input_vods_dir: str = "./input_vods"
    output_vods_dir: str = "./temp"
    cache_dir: str = "./cache/transcripts"
    gemini_cache_dir: str = "./cache/gemini"

    def validate_startup(self):
        if not self.gemini_api_key:
            logging.critical("CRITICAL ERROR: GEMINI_API_KEY environment variable is missing.")
            sys.exit(1)
            
        os.makedirs(self.input_vods_dir, exist_ok=True)
        os.makedirs(self.output_vods_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.gemini_cache_dir, exist_ok=True)

config = Settings()