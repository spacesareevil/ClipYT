import os
import sys
import logging
from dotenv import load_dotenv
from dataclasses import dataclass, field

@dataclass
class Settings:
    load_dotenv()
    # Google OAuth Paths
    client_secrets_file: str = field(default_factory=lambda: os.getenv("YT_CLIENT_SECRETS", "client_secrets.json"))
    token_cache_file: str = field(default_factory=lambda: os.getenv("YT_TOKEN_CACHE", "token.json"))
    layout_cache_file: str = "layout_config.json"
    
    # API Keys
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY"))

    # Webshare Proxy
    webshare_proxy_username: str = field(default_factory=lambda: os.getenv("WEBSHARE_PROXY_USERNAME"))
    webshare_proxy_password: str = field(default_factory=lambda: os.getenv("WEBSHARE_PROXY_PASSWORD"))

    # Google Workspace Targets
    master_drive_folder_id: str = "1G9UwjtRUlkdFbiYY1x-i7qStoc4vSFKy"
    spreadsheet_name: str = "YouTube Live Stream Clips"

    # Local Directory Paths
    input_vods_dir: str = "./input_vods"
    output_vods_dir: str = "./temp"
    cache_dir: str = "./cache/transcripts"
    gemini_cache_dir: str = "./cache/gemini"
    channel_cache_dir: str = "./cache/channels"
    last_channel_cache_file: str = "./cache/channels/last_channel.json"

    def validate_startup(self):
        if not self.gemini_api_key:
            logging.critical("CRITICAL ERROR: GEMINI_API_KEY environment variable is missing.")
            sys.exit(1)
            
        os.makedirs(self.input_vods_dir, exist_ok=True)
        os.makedirs(self.output_vods_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.gemini_cache_dir, exist_ok=True)
        os.makedirs(self.channel_cache_dir, exist_ok=True)

config = Settings()