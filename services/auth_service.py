import os
import pickle
import logging
import gspread
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from config.settings import config

logger = logging.getLogger(__name__)

class GoogleAuthService:
    def __init__(self):
        self.scopes = [
            "https://www.googleapis.com/auth/spreadsheets", 
            "https://www.googleapis.com/auth/drive"
        ]
        self.creds = None
        self.client = None
        self.sheet = None
        self.drive_service = None
        
    def authenticate(self):
        """Handles the OAuth flow and initializes the Google API clients."""
        logger.info("[AUTH] Initializing Google Workspace Authentication...")
        
        if os.path.exists(config.token_cache_file):
            with open(config.token_cache_file, 'rb') as token:
                self.creds = pickle.load(token)
                
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                logger.info("[AUTH] Refreshing expired OAuth token...")
                self.creds.refresh(Request())
            else:
                logger.info("[AUTH] No valid token found. Initiating fresh OAuth flow...")
                flow = InstalledAppFlow.from_client_secrets_file(config.client_secrets_file, self.scopes)
                self.creds = flow.run_local_server(port=0)
                
            with open(config.token_cache_file, 'wb') as token:
                pickle.dump(self.creds, token)

        # Initialize the specific clients
        self.client = gspread.authorize(self.creds)
        self.sheet = self.client.open(config.spreadsheet_name)
        self.drive_service = build('drive', 'v3', credentials=self.creds, cache_discovery=False)
        
        logger.info("[AUTH] Successfully connected to Google Sheets and Google Drive APIs.")
        
    def get_stream_list_tab(self):
        """Returns the master Stream List worksheet."""
        if not self.sheet:
            self.authenticate()
        return self.sheet.worksheet("Stream List")