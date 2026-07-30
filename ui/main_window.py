import os, json, logging, hashlib, time
import tkinter as tk
import customtkinter as ctk
import gspread
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date as dt_date, timezone
from dateutil.relativedelta import relativedelta
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google import genai
from google.genai import types
from tkinter import font
from config.settings import config
from models.clip_models import IngestionAnalysisResult, ClipReviewResult
from utils.filenames import clean_filename, build_clip_filename
from services.youtube_service import extract_youtube_id, fetch_vod_playlist, find_vertical_valid_vods
from services.transcript_service import get_formatted_transcript
from services.drive_service import get_or_create_stream_folder, get_all_filenames_in_drive_folder, upload_to_google_drive
from services.clip_service import slice_local_vod, write_metadata_text_file
from services.validation_service import agentic_clip_review, delete_cached_file, purge_expired_cache
from services.channel_cache_service import load_last_channel, load_channel_playlist_cache, save_last_channel, save_channel_playlist_cache, is_playlist_cache_stale, load_channel_vod_cache
from ui.components.clip_data_grid import ClipDataGrid
from ui.error_popup_window import ErrorPopupWindow
from ui.layout_manager_window import LayoutManagerWindow
from ui.batch_verification_window import BatchVerificationWindow

logger = logging.getLogger(__name__)

class ClipYT(ctk.CTk):
    # Establishes connection to Google, used in __init__
    def connect_to_google(self):
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = None
        if os.path.exists(config.token_cache_file):
            try:
                creds = Credentials.from_authorized_user_file(config.token_cache_file, scopes)
            except Exception as e:
                logger.warning(f"Failed to load credentials from {config.token_cache_file}: {e}")
                creds = None
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except RefreshError as e:
                    logger.warning(f"Failed to refresh token: {e}")
                    if os.path.exists(config.token_cache_file):
                        os.remove(config.token_cache_file)
                    flow = InstalledAppFlow.from_client_secrets_file(config.client_secrets_file, scopes)
                    creds = flow.run_local_server(port=0)
            else:
                flow = InstalledAppFlow.from_client_secrets_file(config.client_secrets_file, scopes)
                creds = flow.run_local_server(port=0)
            with open(config.token_cache_file, 'w') as token:
                token.write(creds.to_json())

        self.client = gspread.authorize(creds)
        self.sheet = self.client.open(config.spreadsheet_name)
        self.drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)
        self.stream_list_tab = self.sheet.worksheet("Stream List")

    # Display Error Popup
    def show_error_popup(self, error_message):
        ErrorPopupWindow(self, error_message)

    # VOD Clip Status Update
    def safe_update_status(self, text, color):
        self.after(0, lambda: self.status_var.set(text))
        self.after(0, lambda: self.status_label.configure(text_color=color))

    # Find VOD Status Update
    def safe_update_channel_scan_status(self, text, color):
        self.after(0, lambda: self.channel_scan_var.set(text))
        self.after(0, lambda: self.channel_scan_label.configure(text_color=color))

    # Batch Processing Status Update
    def safe_update_batch_status(self, text, color):
        self.after(0, lambda: self.batch_status_var.set(text))
        self.after(0, lambda: self.batch_status_label.configure(text_color=color))

    # Batch Status Bar???
    def stop_loading_bar(self):
        self.batch_progress_bar.stop()
        self.batch_progress_bar.grid_remove()

    # Finish Batch UI Setup
    def finalize_batch_ui(self):
        self.is_batch_processing = False
        self.batch_btn.configure(state="normal", text="🎬 Process All Pending Clips")
        self.dropdown.configure(state="normal")
        if hasattr(self, 'source_file_exists') and self.source_file_exists:
            self.check_source_btn.configure(state="disabled")
        else:
            self.check_source_btn.configure(state="normal")

    # Batch Worksheet Dropdown Refresh        
    def refresh_worksheet_dropdowns(self):
        self.stream_titles = self.stream_list_tab.col_values(1)[1:] 
        self.dropdown.configure(values=self.stream_titles, command=self.on_worksheet_selected)
        if self.stream_titles:
            self.dropdown.set(self.stream_titles[0])
            self.on_worksheet_selected(self.stream_titles[0])

    # Batch Worksheet Dropdown Selection Event
    def on_worksheet_selected(self, choice):
        if self.is_batch_processing:
            self.show_error_popup("Batch Lock Error:\n\nCannot transition streams while queues run.")
            return
        self.active_choice = choice
        self.sort_states.clear() 
        self.active_broadcast_date = "" 
        self.executor.submit(self.load_stream_clips)

    # Make Clips Tab - Layout Manager
    def open_layout_manager(self):
        if self.is_batch_processing: return
        LayoutManagerWindow(self, self.current_column_order, self.column_visibility, self.apply_new_column_order)

    # Make Clips Tab - Layout Manager - Reorder Columns
    def apply_new_column_order(self, reordered_list):
        self.current_column_order = reordered_list
        self.refresh_grid_view()

    # Refresh Worksheet Grid
    def refresh_grid_view(self):
        """Prepares the drive cache data and passes it to the grid component."""
        if not hasattr(self, 'current_clips_data') or not self.current_clips_data:
            self.clip_grid.render_data_grid([])
            return

        formatted_data = []
        
        for row in self.current_clips_data:
            title = row.get("Title", "Untitled")
            start = row.get("Timestamp Start", "--:--")
            end = row.get("Timestamp End", "--:--")
            filename = build_clip_filename(row, self.active_choice)

            status = 'Pending'
            if filename in self.current_drive_cache:
                status = 'In Drive'
            elif "New Timestamp Start" in row and row["New Timestamp Start"]:
                status = 'Needs Reslicing (New Timestamps)'
                start = row["New Timestamp Start"]
                end = row["New Timestamp End"]
                
            formatted_data.append({
                'title': title,
                'start_time': start,
                'end_time': end,
                'status': status
            })
            
        # Send the properly packaged data to the grid!
        self.clip_grid.render_data_grid(formatted_data)

    # Check for local VOD
    def recheck_source_file(self):
        if not self.active_choice: return
        
        safe_title = clean_filename(self.active_choice)
        expected_local_vod = os.path.join(config.input_vods_dir, f"{safe_title}.mp4")
        
        if os.path.exists(expected_local_vod):
            self.source_file_exists = True
            self.status_var.set("Status: Active VOD located locally.")
            self.status_label.configure(text_color="#2ecc71")
            self.batch_btn.configure(state="normal")
            self.check_source_btn.configure(state="disabled")
            
            self.refresh_grid_view() 
        else:
            self.show_error_popup(f"File Still Missing:\n\nCould not find '{safe_title}.mp4'\nin the {config.input_vods_dir} folder.\n\nPlease double check the filename exactly matches.")

    # Process All Pending VOD Clips
    def start_batch_process(self):
        self.is_batch_processing = True
        self.batch_btn.configure(state="disabled", text="⏳ Processing Batch Queue...")
        self.dropdown.configure(state="disabled")
        self.executor.submit(self.run_batch_worker)

    # Find Clips from VODs (Find VODs Button)
    def start_channel_scan_thread(self):
        self.safe_update_channel_scan_status(f"Begin Fetching Recent Live VODs", "#2ecc71")
        target_channel = self.channel_input_field.get().strip()
        if not target_channel:
            self.safe_update_channel_scan_status(f"Error Scanning", "#e74c3c")
            self.show_error_popup("Scan Error:\n\nPlease enter a valid channel handle or profile link URL.")
            return
        try:
            days_back = int(self.channel_limit_field.get().strip())
        except ValueError:
            days_back = 30 # Safe fallback if user typed letters
        
        self.scan_channel_btn.configure(state="disabled", text="⏳ Extracting Live VODs...")

        self.executor.submit(self.run_find_vods_worker, target_channel, days_back)

    # Find Clips from VODs (Find VODs Button)    
    def run_find_vods_worker(self, channel, days_back):
        try:
            self.safe_update_channel_scan_status(f"Scanning {channel} for VODs in the last {days_back} days", "#2ecc71")
            force_refresh = self.cache_refresh_checkbox.get()
            save_last_channel(channel)
            playlist_vods = fetch_vod_playlist(channel, days_back, force_refresh)

            # Remove duplicates based on video_id
            seen_ids = set()
            unique_vods = []
            for vod in playlist_vods:
                if vod.video_id not in seen_ids:
                    seen_ids.add(vod.video_id)
                    unique_vods.append(vod)

            #Store the new VODs list after removing duplicates
            self.playlist_vods = unique_vods

            #Filter for Vertical VODs only
            self.safe_update_channel_scan_status(f"Finding VODs for clipping", "#2ecc71")
            self.playlist_vertical_vods = find_vertical_valid_vods(channel, self.playlist_vods, days_back)
            self.safe_update_channel_scan_status(f"Found {len(self.playlist_vertical_vods )} Vertical VODs within the last {days_back} days", "#2ecc71")

            display_titles = [f"[{v['date']}] {v['title']}..." for v in self.playlist_vertical_vods]

            self.after(0, lambda: self.vod_select_dropdown.configure(values=display_titles))
            if display_titles:
                self.after(0, lambda: self.vod_select_dropdown.set(display_titles[0]))
                # --- NEW: Enable the run button since VODs are loaded ---
                self.after(0, lambda: self.run_ai_btn.configure(state="normal"))
            else:
                # --- NEW: Keep disabled if the channel had 0 valid VODs ---
                self.after(0, lambda: self.run_ai_btn.configure(state="disabled"))
            self.safe_update_channel_scan_status(f"{len(display_titles)} VODs Loaded", "#2ecc71")
                
        except Exception as e:
            self.after(0, lambda e_val=e: self.show_error_popup(f"Scan Error:\n\n{str(e_val)}"))
            # Keep disabled if the scan crashes
            self.after(0, lambda: self.run_ai_btn.configure(state="disabled"))
        finally:
            self.after(0, lambda: self.scan_channel_btn.configure(state="normal", text="🔍 Fetch Recent Live VODs"))

    # Store Clips to Google Sheets Button
    def start_ai_ingestion_thread(self):
        title = self.new_stream_title.get().strip()
        date = self.new_stream_date.get().strip()
        poster = self.new_stream_poster.get().strip()
        url = self.new_stream_url.get().strip()
        
        count = self.param_clip_count.get().strip()
        min_sec = self.param_min_sec.get().strip()
        max_sec = self.param_max_sec.get().strip()
        scan_bef = self.param_scan_before.get().strip()
        scan_aft = self.param_scan_after.get().strip()

        selected_idx = self.vod_select_dropdown._values.index(self.vod_select_dropdown._current_value)
        target_vod = self.scraped_vod_options[selected_idx]
        captions_url = target_vod["captions_url"]
        video_id = target_vod["video_id"]
        if not all([title, date, poster, url, count, min_sec, max_sec, scan_bef, scan_aft, captions_url]):
            self.show_error_popup("Validation Error:\n\nAll parameters must be completely filled out for single VOD ingestion.")
            return

        self.run_ai_btn.configure(state="disabled", text="⏳ Running Pipeline Ingestion...")
        self.executor.submit(self.run_single_ai_ingestion, title, captions_url, video_id, date, poster, url, count, min_sec, max_sec, scan_bef, scan_aft)

    # Find & Make All Clips button
    def start_batch_range_thread(self):
        channel = self.batch_channel_field.get().strip()
        months_input = self.batch_range_field.get().strip()
        count = self.batch_clip_count.get().strip()
        min_sec = self.batch_min_sec.get().strip()
        max_sec = self.batch_max_sec.get().strip()
        scan_bef = self.batch_scan_before.get().strip()
        scan_aft = self.batch_scan_after.get().strip()

        if not all([channel, months_input, count, min_sec, max_sec, scan_bef, scan_aft]):
            self.show_error_popup("Validation Error:\n\nPlease specify all timeline automation entries completely.")
            return

        self.is_batch_processing = True
        self.run_batch_range_btn.configure(state="disabled", text="⏳ Scraping Channel (This may take a moment)...")

        self.batch_progress_bar.grid()
        self.batch_progress_bar.start()

        self.executor.submit(self._background_scrape_and_verify, channel, months_input, count, min_sec, max_sec, scan_bef, scan_aft)

    # Find & Make All Clips button
    def _background_scrape_and_verify(self, channel, months_input, count, min_sec, max_sec, scan_bef, scan_aft):
        try:
            lookback_months = int(str(months_input).strip())
            start_threshold = dt_date.today() - relativedelta(months=lookback_months)

            playlist_cache_stale = is_playlist_cache_stale(channel) 
            is_vod_cache_stale = is_vod_cache_stale

            vod_playlist = load_channel_playlist_cache(channel)
            all_scraped_vods = load_channel_vod_cache(channel)

            if vod_playlist & all_scraped_vods is None:
                vod_playlist = fetch_vod_playlist(channel, days_back=start_threshold)
                all_scraped_vods = find_vertical_valid_vods(channel, vod_playlist, start_threshold)

            target_batch = []
            
            for vod in all_scraped_vods:
                try:
                    vod_date = datetime.strptime(vod['date'], '%Y-%m-%d').date()
                    if start_threshold <= vod_date <= dt_date.today():
                        target_batch.append(vod)
                except ValueError:
                    continue
                    
            if not target_batch:
                self.safe_update_batch_status(f"Zero streams matched lookback parameter ({months_input} mos).", "#e67e22")
                self.after(0, self.stop_loading_bar)
                self.after(0, self.finalize_batch_ui)
                return

            self.after(0, self.stop_loading_bar)
            self.after(0, lambda: BatchVerificationWindow(
                parent=self,
                discovered_streams=target_batch,
                existing_titles=self.stream_titles,
                on_confirm_callback=lambda verified_streams: self.execute_verified_batch_processing(
                    verified_streams, count, min_sec, max_sec, scan_bef, scan_aft
                )
            ))
        except Exception as e:
            self.safe_update_batch_status("Scraping failed.", "#e74c3c")
            self.after(0, self.stop_loading_bar)
            self.after(0, lambda err=e: self.show_error_popup(f"Scrape Error:\n\n{str(err)}"))
            self.after(0, self.finalize_batch_ui)

    # Find & Make All Clips Button
    def execute_verified_batch_processing(self, verified_streams, count, min_sec, max_sec, scan_bef, scan_aft):
        if not verified_streams:
            self.finalize_batch_ui()
            return
            
        self.run_batch_range_btn.configure(state="disabled", text="⚙️ Running Batch Automation...")
        self.executor.submit(self.run_batch_range_ingestion, verified_streams, count, min_sec, max_sec, scan_bef, scan_aft)

    # DEAD CODE - NOTHING CALLS THIS METHOD
    def start_single_clip_pipeline(self, local_vod_path, row, filename, target_folder_id):
        self.safe_update_status("Running single processing task...", "#3498db")
        self.executor.submit(self.execute_clip_pipeline, local_vod_path, row, filename, target_folder_id)

    # App / UI Init
    def __init__(self):
        super().__init__()
        self.title("Local Stream Clipper Studio")
        self.geometry("675x1200")
        ctk.set_appearance_mode("dark")
        
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        self.header_font = ctk.CTkFont(family="Consolas", size=24)
        self.label_font = ctk.CTkFont(family="Segoe UI Semibold", size=16)
        self.small_light_font = ctk.CTkFont(family="Segoe UI Light", size=11)
        self.button_font = ctk.CTkFont(family="Consolas", size=16, weight="bold")

        self.raw_headers = []
        self.current_column_order = []
        self.current_clips_data = []
        self.column_visibility = {} 
        self.active_choice = None
        self.active_broadcast_date = "" 
        self.sort_states = {} 
        self.is_batch_processing = False  
        self.scraped_vod_options = []
        self.source_file_exists = False
        
        self.current_local_vod = ""
        self.current_drive_cache = set()
        self.current_folder_id = ""
        
        self.cached_folder_ids = {}

        self.tab_control = ctk.CTkTabview(self)
        self.tab_control.pack(padx=10, pady=10, fill="both", expand=True)
        
        self.find_vods_tab = self.tab_control.add("Find VODs")
        self.studio_tab = self.tab_control.add("Make Clips")
        self.batch_tab = self.tab_control.add("Find & Make All Clips")

        self.setup_find_vod_ui()

        self.setup_studio_ui()
        
        self.setup_batch_range_ui()

        self.connect_to_google()
        self.ai_client = genai.Client(api_key=config.gemini_api_key)

        # Purge any expired file cache entries
        purge_expired_cache(self.ai_client)

        self.refresh_worksheet_dropdowns()

    # Batch Worksheet Dropdown Selection Event
    def _fetch_broadcast_date(self, choice):
        all_streams_meta = self.stream_list_tab.get_all_records()
        for item in all_streams_meta:
            if str(item.get("Title", "")).strip() == choice.strip():
                self.active_broadcast_date = str(item.get("Broadcast Date", item.get("Date", ""))).strip()
                break

    # Batch Worksheet Dropdown Selection Event
    def _fetch_or_create_worksheet(self, choice):
        try:
            target_tab = self.sheet.worksheet(choice)
            all_values = target_tab.get_all_values()
            if all_values:
                self.raw_headers = all_values[0]
                self.current_clips_data = [dict(zip(self.raw_headers, row)) for row in all_values[1:]]
            else:
                self.raw_headers = []
                self.current_clips_data = []

            logger.info(f"[SHEETS] Successfully mapped existing worksheet records for: '{choice}'")
        except gspread.exceptions.WorksheetNotFound:
            logger.warning(f"[SHEETS] Worksheet '{choice}' not found. Creating fallback placeholder tab.")
            target_tab = self.sheet.add_worksheet(title=choice, rows="100", cols="20")
            self.raw_headers = [
                "Live Title", "Timestamp Start", "Timestamp End", "Clip Length (sec)",
                "Viral Score", "On-Screen Hook", "Title", "Description", "Hashtags", "Editing Notes"
            ]
            target_tab.append_row(self.raw_headers)
            self.current_clips_data = []
            try:
                layout_requests = {
                    "requests": [
                        {"setBasicFilter": {"filter": {"range": {"sheetId": target_tab.id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": len(self.raw_headers)}}}},
                        {"autoResizeDimensions": {"dimensions": {"sheetId": target_tab.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": len(self.raw_headers)}}}
                    ]
                }
                self.sheet.batch_update(layout_requests)
                logger.info(f"[SHEETS] Formatted placeholder grid for '{choice}'")
            except Exception as f_err:
                logger.error(f"[SHEETS WARNING] Standalone placeholder style intercept bypassed: {str(f_err)}")

    # Batch Worksheet Dropdown Selection Event
    def _apply_layout_preferences(self):
        if os.path.exists(config.layout_cache_file):
            try:
                with open(config.layout_cache_file, "r", encoding="utf-8") as f:
                    cached_layout = json.load(f)

                cached_order = cached_layout.get("column_order", [])
                cached_visibility = cached_layout.get("column_visibility", {})

                if set(cached_order) == set(self.raw_headers):
                    self.current_column_order = list(cached_order)
                    self.column_visibility = cached_visibility
                    logger.info("[LAYOUT] Successfully injected custom columns from layout config")
                else:
                    self.current_column_order = list(self.raw_headers)
                    self.column_visibility = {h: True for h in self.raw_headers}
            except Exception as cache_err:
                logger.error(f"[LAYOUT CRITICAL] Failed parsing local preferences: {str(cache_err)}")
                self.current_column_order = list(self.raw_headers)
                self.column_visibility = {h: True for h in self.raw_headers}
        else:
            self.current_column_order = list(self.raw_headers)
            for h in self.raw_headers:
                if h not in self.column_visibility:
                    self.column_visibility[h] = True

    # Batch Worksheet Dropdown Selection Event
    def _prepare_drive_folder(self, choice):
        folder_key = f"{self.active_broadcast_date}_{choice}"
        if folder_key not in self.cached_folder_ids:
            self.cached_folder_ids[folder_key] = get_or_create_stream_folder(choice, self.active_broadcast_date, self.drive_service)

        target_folder_id = self.cached_folder_ids[folder_key]
        existing_files_cache = get_all_filenames_in_drive_folder(target_folder_id, self.drive_service)

        self.current_drive_cache = existing_files_cache
        self.current_folder_id = target_folder_id

    # Batch Worksheet Dropdown Selection Event
    def _update_ui_for_local_vod(self, expected_local_vod, safe_title):
        if not os.path.exists(expected_local_vod):
            self.source_file_exists = False
            self.after(0, lambda: self.status_var.set(f"⚠️ Source file missing: '{safe_title}.mp4'"))
            self.after(0, lambda: self.status_label.configure(text_color="#e74c3c"))
            self.after(0, lambda: self.batch_btn.configure(state="disabled"))
            self.after(0, lambda: self.check_source_btn.configure(state="normal"))
        else:
            self.source_file_exists = True
            self.after(0, lambda: self.status_var.set("Status: Active VOD located locally."))
            self.after(0, lambda: self.status_label.configure(text_color="#2ecc71"))
            self.after(0, lambda: self.batch_btn.configure(state="normal"))
            self.after(0, lambda: self.check_source_btn.configure(state="disabled"))

    # Batch Worksheet Dropdown Selection Event
    def load_stream_clips(self):
        choice = self.active_choice
        if not choice: return
        try:
            self.safe_update_status(f"Fetching rows from tab '{choice}'...", "#3498db")

            self._fetch_broadcast_date(choice)
            self._fetch_or_create_worksheet(choice)
            self._apply_layout_preferences()

            safe_title = clean_filename(choice)
            expected_local_vod = os.path.join(config.input_vods_dir, f"{safe_title}.mp4")
            
            self._prepare_drive_folder(choice)
            self._update_ui_for_local_vod(expected_local_vod, safe_title)

            self.current_local_vod = expected_local_vod

            self.after(0, lambda: self.layout_btn.configure(state="normal"))
            self.after(0, self.refresh_grid_view)
            
        except Exception as e:
            self.after(0, lambda e_val=e: self.show_error_popup(f"Data Retrieval Exception:\n{str(e_val)}"))

    # Make VOD Clips UI Setup
    def setup_studio_ui(self):
        self.studio_tab.grid_columnconfigure(0, weight=1)
        self.studio_tab.grid_rowconfigure(2, weight=1)

        # 1. MUST BUILD THE WALL FIRST: Create the top_bar frame
        self.top_bar = ctk.CTkFrame(self.studio_tab) 
        self.top_bar.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew") # Adjust row/column if needed

        # 2. NOW HANG THE PICTURE: Add the label inside self.top_bar
        self.label = ctk.CTkLabel(self.top_bar, text="Select Active Stream Grid:", font=self.label_font)
        self.label.grid(row=0, column=0, padx=10, pady=10) # Adjust grid settings as needed

        # --- NEW UI TOGGLE ---
        self.enable_qa_var = ctk.StringVar(value="off")
        self.qa_checkbox = ctk.CTkCheckBox(self.top_bar, text="🤖 Enable Agentic QA", variable=self.enable_qa_var, onvalue="on", offvalue="off")
        self.qa_checkbox.grid(row=0, column=1, padx=10, pady=10, sticky="e")

        self.batch_btn = ctk.CTkButton(self.top_bar, text="🎬 Process All Pending Clips", fg_color="#2ecc71", hover_color="#27ae60", width=190, state="disabled", command=self.start_batch_process)
        self.batch_btn.grid(row=0, column=2, padx=10, pady=10, sticky="e")

        self.check_source_btn = ctk.CTkButton(self.top_bar, text="🔄 Check for Source", fg_color="#e67e22", hover_color="#d35400", width=150, state="disabled", command=self.recheck_source_file)
        self.check_source_btn.grid(row=0, column=3, padx=10, pady=10, sticky="e")

        self.layout_btn = ctk.CTkButton(self.top_bar, text="⚙️ Manage Layout", width=130, state="disabled", command=self.open_layout_manager)
        self.layout_btn.grid(row=0, column=4, padx=10, pady=10, sticky="e")

        self.dropdown = ctk.CTkOptionMenu(self.studio_tab, values=["Loading lists..."])
        self.dropdown.grid(row=1, column=0, padx=20, pady=5, sticky="ew")

                # 3. AND THEN ADD THE NEW GRID WE JUST MADE
        self.clip_grid = ClipDataGrid(self.studio_tab, width=900, height=500) 
        self.clip_grid.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="nsew")

        self.status_var = tk.StringVar(value="Status: Ready")
        self.status_label = ctk.CTkLabel(self.studio_tab, textvariable=self.status_var, font=self.small_light_font)
        self.status_label.grid(row=3, column=0, padx=20, pady=10, sticky="w")

    # Find VOD UI Setup
    def setup_find_vod_ui(self):
        self.find_vods_tab.grid_columnconfigure(0, weight=1)
        
        # --- FINDVOD CHANNEL FRAME
        findvod_channel_frame = ctk.CTkFrame(self.find_vods_tab)
        findvod_channel_frame.grid(row=0, column=0, padx=20, sticky="ew")

        ctk.CTkLabel(findvod_channel_frame, text="YouTube Channel Handle/URL:", font=self.label_font).grid(row=0, column=0, padx=15, pady=(15, 5), sticky="w")
        
        self.channel_input_field = ctk.CTkEntry(findvod_channel_frame, placeholder_text="e.g., @<ChannelName> or Channel URL", font=self.label_font)
        # Set sticky="ew" so the text box stretches dynamically to fill the empty space
        self.channel_input_field.grid(row=0, column=1, columnspan=3, padx=5, pady=(15, 5), sticky="ew")
        last_channel = load_last_channel()
        if last_channel:
            self.channel_input_field.insert(0, last_channel)
            cached_vods = load_channel_vod_cache(last_channel)
            if cached_vods:
                self.scraped_vod_options = cached_vods
                display_titles = [f"[{v['date']}] {v['title']}..." for v in self.scraped_vod_options]
                
                # Setup dropdown and ai logic if cache exists
                self.after(0, lambda: self.vod_select_dropdown.configure(values=display_titles))
                self.after(0, lambda: self.vod_select_dropdown.set(display_titles[0]))
                self.after(0, lambda: self.run_ai_btn.configure(state="normal"))
                self.after(0, lambda: self.safe_update_channel_scan_status(f"Loaded {len(cached_vods)} VODs from cache for {last_channel}", "#2ecc71"))  

        ctk.CTkLabel(findvod_channel_frame, text="Scan Window:", font=self.label_font).grid(row=1, column=0, padx=(40, 1), pady=(15, 5), sticky="ew")
        self.channel_limit_field = ctk.CTkEntry(findvod_channel_frame, width=50, font=self.label_font)
        self.channel_limit_field.insert(0, "30")
        self.channel_limit_field.grid(row=1, column=1, padx=(5, 5), pady=(15, 5), sticky="ew")
        ctk.CTkLabel(findvod_channel_frame, text="Days", font=self.label_font).grid(row=1, column=2, padx=(1, 40), pady=(15, 5), sticky="ew")

        self.cache_refresh_checkbox = ctk.CTkCheckBox(findvod_channel_frame, text="Force Cache Refresh", onvalue=True, offvalue=False, font=self.label_font)
        self.cache_refresh_checkbox.grid(row=1, column=3, padx=(1, 40), pady=(15, 5), sticky="ew")

        # FINDVOD BUTTON FRAME
        findvod_searchbutton_frame = ctk.CTkFrame(self.find_vods_tab)
        findvod_searchbutton_frame.grid(row=1, column=0, padx=20, sticky="ew")
        findvod_searchbutton_frame.columnconfigure((0,4), weight=1)

        self.scan_channel_btn = ctk.CTkButton(findvod_searchbutton_frame, text="🔍 Find VODs", font=self.button_font, command=self.start_channel_scan_thread)
        self.scan_channel_btn.grid(row=0, column=1, columnspan=2, padx=(15, 5), pady=(15, 5), ipady=30, ipadx=100, sticky="ew") 

        # FINDVOD DROPDOWN FRAME
        findvod_dropdown_frame = ctk.CTkFrame(self.find_vods_tab)
        findvod_dropdown_frame.grid(row=2, column=0, padx=20, sticky="ew")
        findvod_dropdown_frame.columnconfigure(1, weight=1)

        ctk.CTkLabel(findvod_dropdown_frame, text="Select Target Video:", font=self.label_font).grid(row=0, column=0, padx=15, pady=(15, 5), sticky="w")
        
        self.vod_select_dropdown = ctk.CTkOptionMenu(findvod_dropdown_frame, values=["Scan channel first..."], font=self.label_font)
        self.vod_select_dropdown.grid(row=0, column=1, padx=5, pady=(15, 5), sticky="ew")

        # --- CLIPPING CONTROL FRAME
        clip_control_frame = ctk.CTkFrame(self.find_vods_tab)
        clip_control_frame.grid(row=3, column=0, padx=20, pady=10, sticky="ew")
    
        
        ctk.CTkLabel(clip_control_frame, text="VOD Clipping Controls", font=self.label_font).grid(row=0, column=0, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(clip_control_frame, text="Target Clip Count:", font=self.label_font).grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        self.param_clip_count = ctk.CTkEntry(clip_control_frame, width=60)
        self.param_clip_count.insert(0, "10")
        self.param_clip_count.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ctk.CTkLabel(clip_control_frame, text="Clip Size Limits (Sec):", font=self.label_font).grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        ctk.CTkLabel(clip_control_frame, text="Min", font=self.label_font).grid(row=2, column=1, padx=10, pady=5, sticky="ew")       
        self.param_min_sec = ctk.CTkEntry(clip_control_frame, width=50)
        self.param_min_sec.insert(0, "60")
        self.param_min_sec.grid(row=2, column=2, padx=10, pady=5, sticky="ew")
        ctk.CTkLabel(clip_control_frame, text="Max", font=self.label_font).grid(row=3, column=1, padx=10, pady=5, sticky="ew") 
        self.param_max_sec = ctk.CTkEntry(clip_control_frame, width=50)
        self.param_max_sec.insert(0, "180")
        self.param_max_sec.grid(row=3, column=2, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(clip_control_frame, text="Context Window Scan (Sec):", font=self.label_font).grid(row=4, column=0, padx=10, pady=5, sticky="e")        
        ctk.CTkLabel(clip_control_frame, text=" Before", font=self.label_font).grid(row=4, column=1, padx=10, pady=5, sticky="e")
        self.param_scan_before = ctk.CTkEntry(clip_control_frame, width=50)
        self.param_scan_before.insert(0, "60")
        self.param_scan_before.grid(row=4, column=2, padx=10, pady=5, sticky="ew")
        ctk.CTkLabel(clip_control_frame, text="After", font=self.label_font).grid(row=5, column=1, padx=10, pady=5, sticky="e")
        self.param_scan_after = ctk.CTkEntry(clip_control_frame, width=50)
        self.param_scan_after.insert(0, "60")
        self.param_scan_after.grid(row=5, column=2, padx=10, pady=5, sticky="ew")

        ### --- MAKE CLIPS BUTTON

        self.run_ai_btn = ctk.CTkButton(clip_control_frame, text="🎬 Find clips from YouTube VOD and save to Google Sheets", font=self.button_font, fg_color="#2ecc71", hover_color="#27ae60", height=45, state="disabled", command=self.start_ai_ingestion_thread)
        self.run_ai_btn.grid(row=6, column=0, columnspan=4, padx=20, pady=20, sticky="ew")

        #ROW 3

        self.channel_scan_var = tk.StringVar(value="Status: Waiting for YouTube Channel Name or URL")
        self.channel_scan_label = ctk.CTkLabel(self.find_vods_tab, textvariable=self.channel_scan_var, font=("Helvetica", 12, "italic"))
        self.channel_scan_label.grid(row=4, column=0, padx=20, pady=5, sticky="w")

    # Batch Process UI Setup
    def setup_batch_range_ui(self):
        self.batch_tab.grid_columnconfigure(0, weight=1)

        info_box = ctk.CTkFrame(self.batch_tab)
        info_box.grid(row=0, column=0, padx=20, pady=15, sticky="ew")
        
        lbl = ctk.CTkLabel(info_box, text="Batch Make Clips Automation Studio", font=self.header_font, text_color="#3498db")
        lbl.pack(padx=15, pady=(10, 2), anchor="w")
        sub_lbl = ctk.CTkLabel(info_box, text="Asynchronously scrapes target metrics backwards from today's system calendar date across channel history segments.", font=("Helvetica", 11), text_color="#95a5a6")
        sub_lbl.pack(padx=15, pady=(0, 10), anchor="w")

        config_frame = ctk.CTkFrame(self.batch_tab)
        config_frame.grid(row=1, column=0, padx=20, pady=5, sticky="nsew")

        ctk.CTkLabel(config_frame, text="Target Channel Handle:", font=("Helvetica", 11, "bold")).grid(row=0, column=0, padx=15, pady=15, sticky="e")
        self.batch_channel_field = ctk.CTkEntry(config_frame, placeholder_text="@SpacesAreEvil", width=220)
        self.batch_channel_field.grid(row=0, column=1, padx=5, pady=15, sticky="w")
        self.batch_channel_field.insert(0, "@SpacesAreEvil")

        ctk.CTkLabel(config_frame, text="Months To Look Back:", font=("Helvetica", 11, "bold")).grid(row=0, column=2, padx=15, pady=15, sticky="e")
        self.batch_range_field = ctk.CTkEntry(config_frame, placeholder_text="e.g., 1 or 12", width=100)
        self.batch_range_field.grid(row=0, column=3, padx=5, pady=15, sticky="w")
        self.batch_range_field.insert(0, "1")

        ctk.CTkLabel(config_frame, text="Clips Per VOD:", font=("Helvetica", 11, "bold")).grid(row=1, column=0, padx=15, pady=10, sticky="e")
        self.batch_clip_count = ctk.CTkEntry(config_frame, width=60)
        self.batch_clip_count.grid(row=1, column=1, padx=5, pady=10, sticky="w")
        self.batch_clip_count.insert(0, "10")

        ctk.CTkLabel(config_frame, text="Clip Size Boundaries (Sec):", font=("Helvetica", 11, "bold")).grid(row=1, column=2, padx=15, pady=10, sticky="e")
        b_size_frame = ctk.CTkFrame(config_frame, fg_color="transparent")
        b_size_frame.grid(row=1, column=3, sticky="w")
        
        self.batch_min_sec = ctk.CTkEntry(b_size_frame, width=50)
        self.batch_min_sec.insert(0, "60")
        self.batch_min_sec.pack(side="left")
        ctk.CTkLabel(b_size_frame, text=" Min / Max ").pack(side="left", padx=5)
        self.batch_max_sec = ctk.CTkEntry(b_size_frame, width=50)
        self.batch_max_sec.insert(0, "180")
        self.batch_max_sec.pack(side="left")

        ctk.CTkLabel(config_frame, text="Context Window Scan (Sec):", font=("Helvetica", 11, "bold")).grid(row=2, column=0, padx=15, pady=10, sticky="e")
        scan_bounds_frame = ctk.CTkFrame(config_frame, fg_color="transparent")
        scan_bounds_frame.grid(row=2, column=1, sticky="w")

        self.batch_scan_before = ctk.CTkEntry(scan_bounds_frame, width=50)
        self.batch_scan_before.insert(0, "60")
        self.batch_scan_before.pack(side="left")
        ctk.CTkLabel(scan_bounds_frame, text=" Before / After ").pack(side="left", padx=5)
        self.batch_scan_after = ctk.CTkEntry(scan_bounds_frame, width=50)
        self.batch_scan_after.insert(0, "60")
        self.batch_scan_after.pack(side="left")

        self.run_batch_range_btn = ctk.CTkButton(self.batch_tab, text="🚀 Find & Make All Clips", fg_color="#3498db", hover_color="#2980b9", height=45, command=self.start_batch_range_thread)
        self.run_batch_range_btn.grid(row=3, column=0, columnspan=4, padx=20, pady=25, sticky="ew")

        self.batch_status_var = tk.StringVar(value="Batch Status: System idle. Ready to query timeline ranges.")
        self.batch_status_label = ctk.CTkLabel(self.batch_tab, textvariable=self.batch_status_var, font=("Helvetica", 12, "italic"))
        self.batch_status_label.grid(row=4, column=0, padx=20, pady=5, sticky="w")

        self.batch_progress_bar = ctk.CTkProgressBar(self.batch_tab, mode="indeterminate", width=300)
        self.batch_progress_bar.grid(row=5, column=0, padx=20, pady=5, sticky="w")
        self.batch_progress_bar.set(0)
        self.batch_progress_bar.grid_remove() 

    # Process All Pending VOD Clips
    def run_batch_worker(self):
        safe_title = clean_filename(self.active_choice)
        expected_local_vod = os.path.join(config.input_vods_dir, f"{safe_title}.mp4")
        pending_clips = []
        
        logger.info(f"[BATCH WORKER] Starting process worker loop for target tab: '{self.active_choice}'")
        self.safe_update_status("Batch Status: Checking destination...", "#3498db")
        
        folder_key = f"{self.active_broadcast_date}_{self.active_choice}"
        target_folder_id = self.cached_folder_ids.get(folder_key) or get_or_create_stream_folder(self.active_choice, self.active_broadcast_date, self.drive_service)
        
        existing_files = get_all_filenames_in_drive_folder(target_folder_id, self.drive_service)

        for row in self.current_clips_data:
            start = str(row.get("Timestamp Start", ""))
            end = str(row.get("Timestamp End", ""))
            if not start or not end: continue
            
            filename = build_clip_filename(row, self.active_choice)
            if filename not in existing_files:
                # Always re-append pending rows, whether they are fresh or need reslicing
                pending_clips.append((row, filename))

        total_count = len(pending_clips)
        logger.info(f"[BATCH WORKER] Verification complete. Found {total_count} pending items to render.")
        
        if total_count == 0:
            self.safe_update_status("Batch Complete: All items up to date.", "#2ecc71")
            self.after(0, self.finalize_batch_ui)
            return

        # Safely extract valid credentials
        worker_creds = None
        if hasattr(self, 'drive_service') and self.drive_service:
            if hasattr(self.drive_service, '_credentials'):
                worker_creds = self.drive_service._credentials
            elif hasattr(self.drive_service, '_http') and hasattr(self.drive_service._http, 'credentials'):
                worker_creds = self.drive_service._http.credentials

        if not worker_creds and hasattr(self, 'client') and hasattr(self.client, 'auth'):
            worker_creds = self.client.auth

        def upload_and_cleanup(staging, txt, f_name, t_folder_id, t_name, credentials):
            try:
                # build a new service client for this thread using pre-fetched valid credentials
                thread_drive_service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
                
                upload_to_google_drive(staging, f_name, 'video/mp4', t_folder_id, thread_drive_service)
                upload_to_google_drive(txt, t_name, 'text/plain', t_folder_id, thread_drive_service)
            except Exception as e:
                raise e
            finally:
                for temp_file in (staging, txt):
                    if os.path.exists(temp_file):
                        try:
                            os.remove(temp_file)
                        except OSError as e:
                            logger.warning(f"[CLEANUP WARNING] Could not remove temp file {temp_file}: {e}")

        upload_futures = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            for sequence_idx, (row, filename) in enumerate(pending_clips, start=1):
                needs_reslice = "New Timestamp Start" in row and row["New Timestamp Start"]

                # If it already failed and has new timestamps, use them for the final slice
                start = row.get("New Timestamp Start") if needs_reslice else str(row.get("Timestamp Start", ""))
                end = row.get("New Timestamp End") if needs_reslice else str(row.get("Timestamp End", ""))

                local_input_path = expected_local_vod # Ensure we use the full path to the video file
                local_staging_path = os.path.abspath(os.path.join(config.output_vods_dir, filename))
                local_txt_path = os.path.abspath(os.path.join(config.output_vods_dir, filename.replace(".mp4", ".txt")))
                txt_filename = filename.replace(".mp4", ".txt")

                try:
                    logger.info(f"Executing manual cut for {filename} using {start} - {end}")
                    slice_local_vod(local_input_path, start, end, local_staging_path)

                    skip_upload = False

                    # --- AGENTIC QA INJECTION ---
                    if self.enable_qa_var.get() == "on" and not needs_reslice:
                        self.safe_update_status("Running Agentic QA Review...", "#9b59b6")
                        review_data = agentic_clip_review(self.ai_client, local_staging_path, local_input_path, row)
                        if review_data:
                            row["QA Grade"] = review_data.get("grade")
                            row["QA Visual Description"] = review_data.get("visual_description")
                            row["QA Is Match"] = review_data.get("is_match")
                            row["QA Feedback"] = review_data.get("feedback")

                            new_start = review_data.get("new_start_time")
                            new_end = review_data.get("new_end_time")

                            # If it failed match OR gave new timestamps, we mark it for reslice and DON'T upload yet
                            if not review_data.get("is_match") or (new_start and new_end):
                                logger.info(f"Clip {filename} needs reslicing based on QA review.")
                                skip_upload = True

                                if new_start and new_end:
                                    row["New Timestamp Start"] = new_start
                                    row["New Timestamp End"] = new_end

                                filename = f"[QA_FAIL]_{filename}"
                                txt_filename = f"[QA_FAIL]_{txt_filename}"

                                # Immediately refresh the grid to show "Needs Reslicing" status
                                self.after(0, self.refresh_grid_view)
                    # ---------------------------

                    # If this was a reslice pass, we clean up the cached Gemini file
                    if needs_reslice:
                        delete_cached_file(self.ai_client, expected_local_vod, str(row.get("Timestamp Start", "")), str(row.get("Timestamp End", "")))
                        # Clear new timestamps so it shows as 'In Drive' on next refresh
                        row["New Timestamp Start"] = ""
                        row["New Timestamp End"] = ""

                    write_metadata_text_file(row, local_txt_path)

                    if not skip_upload:
                        logger.info(f"Queueing upload for {filename} to Drive...")
                        self.safe_update_status(f"Queueing {filename} upload...", "#3498db")
                        future = executor.submit(
                            upload_and_cleanup, local_staging_path, local_txt_path, filename, target_folder_id, txt_filename, worker_creds
                        )
                        upload_futures.append((future, filename))
                    else:
                        logger.info(f"Skipping upload for {filename} pending user reslice trigger. Purging local chunk.")
                        self.safe_update_status(f"Clip needs reslice. Upload delayed.", "#f39c12")
                        # Explicitly purge the local chunks if upload is skipped to save disk space
                        for temp_file in (local_staging_path, local_txt_path):
                            if os.path.exists(temp_file):
                                try:
                                    os.remove(temp_file)
                                except OSError as e:
                                    logger.warning(f"[CLEANUP WARNING] Could not remove temp file {temp_file}: {e}")

                except Exception as row_err:
                    logger.error(f"[BATCH WORKER] Task error on item {filename}: {str(row_err)}")
                    self.after(0, lambda f=filename, e=row_err: self.show_error_popup(f"Batch Exception on Item {f}:\n\n{str(e)}"))
                    for temp_file in (local_staging_path, local_txt_path):
                        if os.path.exists(temp_file):
                            try:
                                os.remove(temp_file)
                            except OSError as e:
                                logger.warning(f"[CLEANUP WARNING] Could not remove temp file {temp_file}: {e}")

            for future, fname in upload_futures:
                try:
                    future.result()
                except Exception as upload_err:
                    logger.error(f"[BATCH WORKER] Upload error on item {fname}: {str(upload_err)}")
                    self.after(0, lambda f=fname, e=upload_err: self.show_error_popup(f"Batch Upload Exception on Item {f}:\n\n{str(e)}"))

        self.safe_update_status("Batch Success!", "#2ecc71")
        self.after(0, self.finalize_batch_ui)

    # Store Clips to Google Sheets Button
    def run_single_ai_ingestion(self, title, caption_url, video_id, date, poster, url, count, min_sec, max_sec, scan_bef, scan_aft):
        try:
            logger.info(f"[GEMINI PIPELINE] Initializing single pass ingestion for: '{title}'")

            self.safe_update_channel_scan_status("Extracting stream captions...", "#3498db")
            transcript_payload = get_formatted_transcript(video_id, caption_url)

            self.safe_update_channel_scan_status("Analyzing retention with Gemini...", "#3498db")
            clip_rows = self._query_gemini_strategist(transcript_payload, title, poster, url, count, min_sec, max_sec, scan_bef, scan_aft)

            if not clip_rows:
                raise ValueError("Gemini complete but zero clips matched parameters.")

            self.safe_update_channel_scan_status("Syncing workspace structures...", "#e67e22")
            self._commit_clips_to_spreadsheet(title, date, url, clip_rows)
            
            self.safe_update_channel_scan_status("Success! Stream ingested.", "#2ecc71")
            self.after(0, lambda: self.new_stream_title.delete(0, tk.END))
            self.after(0, lambda: self.new_stream_url.delete(0, tk.END))
            self.after(0, self.refresh_worksheet_dropdowns)

        except Exception as ai_err:
            logger.error(f"[GEMINI PIPELINE CRITICAL] Ingestion failed: {str(ai_err)}")
            self.safe_update_channel_scan_status("Ingestion Pipeline Crash.", "#e74c3c")
            self.after(0, lambda e=ai_err: self.show_error_popup(f"AI Ingestion Pipeline Crash:\n\n{str(e)}"))
        finally:
            self.after(0, lambda: self.run_ai_btn.configure(state="normal", text="🎬 Find clips from YouTube VOD and save to Google Sheets"))

    # Find & Make All Clips Button
    def run_batch_range_ingestion(self, verified_batch, count, min_sec, max_sec, scan_bef, scan_aft):
        try:
            total_batch_count = len(verified_batch)
            logger.info(f"[BATCH PIPELINE] Processing {total_batch_count} verified long-form vertical assets.")
            
            for batch_idx, current_vod in enumerate(verified_batch, start=1):
                vod_title = clean_filename(current_vod['title'])
                vod_date_str = current_vod['date']
                vod_url = current_vod['url']
                vod_creator = current_vod['creator']
                captions_url = current_vod.get('captions_url')
                
                if vod_title in self.stream_titles:
                    logger.info(f"[BATCH PIPELINE] Skipping '{vod_title}' — already exists in Stream List.")
                    self.safe_update_batch_status(f"Skipping [{batch_idx}/{total_batch_count}]: '{vod_title[:20]}...' (Already Processed)", "#e67e22")
                    continue
                
                logger.info(f"[BATCH PIPELINE] [{batch_idx}/{total_batch_count}]: Ingesting video asset '{vod_title}'")
                self.safe_update_batch_status(f"Batch Ingest [{batch_idx}/{total_batch_count}]: Subtitles for '{vod_title[:15]}...'...", "#3498db")
                
                video_id = extract_youtube_id(vod_url)
                if not video_id: continue

                try:
                    transcript_payload = get_formatted_transcript(video_id, captions_url)
                except Exception as tx_err:
                    logger.error(f"[BATCH PIPELINE] Skipping VOD '{vod_title}' — Subtitle tracks not found: {str(tx_err)}")
                    continue

                self.safe_update_batch_status(f"Batch Ingest [{batch_idx}/{total_batch_count}]: Running Gemini analysis...", "#3498db")
                clip_rows = self._query_gemini_strategist(transcript_payload, vod_title, vod_creator, vod_url, count, min_sec, max_sec, scan_bef, scan_aft)

                if not clip_rows:
                    logger.warning(f"[BATCH PIPELINE] No matching high-retention highlights isolated for stream: {vod_title}")
                    continue

                self.safe_update_batch_status(f"Batch Ingest [{batch_idx}/{total_batch_count}]: Syncing workbook tab...", "#e67e22")
                self._commit_clips_to_spreadsheet(vod_title, vod_date_str, vod_url, clip_rows)

            self.safe_update_batch_status(f"Batch clear! Ingested {total_batch_count} historical VOD tracks.", "#2ecc71")
            self.after(0, self.refresh_worksheet_dropdowns)

        except Exception as batch_err:
            logger.error(f"[BATCH PIPELINE CRITICAL] Historical lookup crash: {str(batch_err)}")
            self.safe_update_batch_status("Batch Lookback Pipeline Failed.", "#e74c3c")
            self.after(0, lambda e=batch_err: self.show_error_popup(f"Historical Lookup Crash:\n\n{str(e)}"))
        finally:
            self.after(0, self.finalize_batch_ui)
            self.after(0, lambda: self.run_batch_range_btn.configure(state="normal", text="🚀 Find & Make All Clips"))

    # Store Clips to Google Sheets Button
    def _query_gemini_strategist(self, transcript_payload, title, creator, url, count, min_sec, max_sec, scan_bef, scan_aft):
        transcript_hash = hashlib.sha256(transcript_payload.encode('utf-8')).hexdigest()
        video_id = url.split("v=")[-1] if "v=" in url else "unknown_video"
        
        param_signature = f"{count}_{min_sec}_{max_sec}_{scan_bef}_{scan_aft}"
        cache_filename = f"{video_id}_{transcript_hash[:16]}_{param_signature}.json"
        cache_path = os.path.join(config.gemini_cache_dir, cache_filename)

        if os.path.exists(cache_path):
            logger.info(f"[GEMINI CACHE] Found pristine cached analysis for Video ID: {video_id}. Skipping remote API payload transfer.")
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as cache_read_err:
                logger.error(f"[GEMINI CACHE WARNING] Failed to read cache file, proceeding to hot API fetch: {str(cache_read_err)}")

        system_instruction = (
            "You are a viral short-form content strategist. Extract HIGH-RETENTION, VIRAL clips from the provided transcript.\n"
            "Criteria: emotional spikes, bold statements, story arcs, debate, reactions, inside jokes.\n\n"
            "Strict Constraints:\n"
            "- Do NOT invent, fabricate, or combine non-sequential clips.\n"
            "- Timestamps: strictly HH:MM:SS or MM:SS format.\n"
            "- Timestamps must be verbatim, chronological, non-overlapping, and mathematically valid.\n"
            "- Flag misalignments; do NOT estimate/round.\n"
            "- Add trim/reorder/hook/filler instructions to the 'editing_notes' field.\n"
            "- 'viral_score' must be a percentage string (e.g., '85%')."
        )

        user_prompt = (
            f"Target: Top {count} clips.\n"
            f"Length Constraints: {min_sec}-{max_sec} seconds.\n"
            f"Context Window: Include related footage {scan_bef}s before and {scan_aft}s after the core viral moment.\n"
            f"Live Title: {title}\n"
            f"Creator: {creator}\n"
            f"URL: {url}\n\n"
            f"TRANSCRIPT:\n{transcript_payload}"
        )

        logger.info(f"[GEMINI API] Transmitting payload to Gemini 2.5 Flash model. Prompt size: ~{len(transcript_payload)} characters.")
        
        response = self.ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=IngestionAnalysisResult,
                temperature=0.15
            )
        )
        
        logger.info(f"[GEMINI API] Successfully parsed JSON response from Gemini model.")
        extracted_clips = json.loads(response.text).get("clips", [])
        
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(extracted_clips, f, ensure_ascii=False, indent=4)
            logger.info(f"[GEMINI CACHE] Successfully committed analysis payload to disk for future runs.")
        except Exception as cache_write_err:
            logger.error(f"[GEMINI CACHE WARNING] Could not write execution log to disk: {str(cache_write_err)}")

        return extracted_clips

    #run_single_range_ingestion and run_batch_range_ingestion
    def _commit_clips_to_spreadsheet(self, title, date_str, url, clip_rows):
        is_new_tab = False
        headers = [
            "Live Title", "Timestamp Start", "Timestamp End", "Clip Length (sec)", 
            "Viral Score", "On-Screen Hook", "Title", "Description", "Hashtags", "Editing Notes"
        ]
        
        try:
            new_tab = self.sheet.add_worksheet(title=title, rows="100", cols="20")
            is_new_tab = True
        except gspread.exceptions.APIError as sheet_err:
            if "already exists" in str(sheet_err):
                new_tab = self.sheet.worksheet(title)
            else:
                raise sheet_err

        new_tab_gid = new_tab.id
        sheet_hyperlink_formula = f'=HYPERLINK("#gid={new_tab_gid}&range=A1", "{title}")'

        self.stream_list_tab.append_row(
            [title, date_str, sheet_hyperlink_formula, url],
            value_input_option="USER_ENTERED"
        )

        sheet_payload = []
        for item in clip_rows:
            sheet_payload.append([
                item.get("live_title", title),
                item.get("timestamp_start", "00:00"),
                item.get("timestamp_end", "01:00"),
                item.get("clip_length_sec", 60),
                item.get("viral_score", "85%"),
                item.get("on_screen_hook", ""),
                item.get("title", "Untitled Segment"),
                item.get("description", ""),
                item.get("hashtags", ""),
                item.get("editing_notes", "")
            ])

        if is_new_tab:
            logger.info(f"[SHEETS] Batch appending headers and {len(clip_rows)} new clip rows to '{title}'")
            new_tab.append_rows([headers] + sheet_payload)
        else:
            logger.info(f"[SHEETS] Appending {len(clip_rows)} new clip rows to existing tab '{title}'")
            new_tab.append_rows(sheet_payload)

        try:
            row_offset = 2 if is_new_tab else 1 
            layout_requests = {
                "requests": [
                    {"setBasicFilter": {"filter": {"range": {"sheetId": new_tab_gid, "startRowIndex": 0, "endRowIndex": len(sheet_payload) + row_offset, "startColumnIndex": 0, "endColumnIndex": len(headers)}}}},
                    {"autoResizeDimensions": {"dimensions": {"sheetId": new_tab_gid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": len(headers)}}}
                ]
            }
            self.sheet.batch_update(layout_requests)
        except Exception as format_err:
            logger.error(f"[SHEETS WARNING] Layout bypass on '{title}': {str(format_err)}")

    #start_single_clip_pipeline which is DEAD CODE
    def execute_clip_pipeline(self, local_vod_path, row, filename, target_folder_id):
        needs_reslice = "New Timestamp Start" in row and row["New Timestamp Start"]

        start = row.get("New Timestamp Start") if needs_reslice else str(row.get("Timestamp Start", ""))
        end = row.get("New Timestamp End") if needs_reslice else str(row.get("Timestamp End", ""))

        vod_filename = os.path.abspath(os.path.join(config.output_vods_dir, filename))
        local_txt_path = os.path.abspath(os.path.join(config.output_vods_dir, filename.replace(".mp4", ".txt")))
        txt_filename = filename.replace(".mp4", ".txt")
        
        try:
            logger.info(f"Executing manual cut for {filename} using {start} - {end}")
            slice_local_vod(local_vod_path, start, end, vod_filename)
            
            skip_upload = False

            # --- AGENTIC QA INJECTION ---
            if self.enable_qa_var.get() == "on" and not needs_reslice:
                self.safe_update_status("Running Agentic QA Review...", "#9b59b6")
                review_data = agentic_clip_review(self.ai_client, vod_filename, local_vod_path, row)
                if review_data:
                    row["QA Grade"] = review_data.get("grade")
                    row["QA Visual Description"] = review_data.get("visual_description")
                    row["QA Is Match"] = review_data.get("is_match")
                    row["QA Feedback"] = review_data.get("feedback")
                    
                    new_start = review_data.get("new_start_time")
                    new_end = review_data.get("new_end_time")

                    if not review_data.get("is_match") or (new_start and new_end):
                        logger.info(f"Clip {filename} needs reslicing based on QA review.")
                        skip_upload = True

                        if new_start and new_end:
                            row["New Timestamp Start"] = new_start
                            row["New Timestamp End"] = new_end

                        filename = f"[QA_FAIL]_{filename}"
                        txt_filename = f"[QA_FAIL]_{txt_filename}"

                        self.after(0, self.refresh_grid_view)
            # ---------------------------

            if needs_reslice:
                delete_cached_file(self.ai_client, local_vod_path, str(row.get("Timestamp Start", "")), str(row.get("Timestamp End", "")))
                row["New Timestamp Start"] = ""
                row["New Timestamp End"] = ""

            write_metadata_text_file(row, local_txt_path)
            
            if not skip_upload:
                logger.info("Uploading asset data to Drive...")
                self.safe_update_status("Uploading to Drive...", "#3498db")
                upload_to_google_drive(vod_filename, filename, 'video/mp4', target_folder_id, self.drive_service)
                upload_to_google_drive(local_txt_path, txt_filename, 'text/plain', target_folder_id, self.drive_service)

                self.safe_update_status("Success!", "#2ecc71")
                
                self.current_drive_cache.add(filename)
                self.current_drive_cache.add(txt_filename)
                self.after(0, self.refresh_grid_view)
            else:
                logger.info(f"Skipping upload for {filename} pending user reslice trigger.")
                self.safe_update_status(f"Clip needs reslice. Upload delayed.", "#f39c12")
            
        except Exception as err:
            logger.error(f"Pipeline error: {str(err)}")
            self.safe_update_status("Pipeline Failure.", "#e74c3c")
            self.after(0, lambda e=err: self.show_error_popup(f"Pipeline Breakdown:\n\n{str(e)}"))
            
        finally:
            for temp_file in (vod_filename, local_txt_path):
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except OSError as e:
                        logger.warning(f"[CLEANUP WARNING] Could not remove temp file {temp_file}: {e}")