import os, json, pickle, logging, hashlib, time
import tkinter as tk
import customtkinter as ctk
import gspread
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date as dt_date
from dateutil.relativedelta import relativedelta
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google import genai
from google.genai import types

from config.settings import config
from models.clip_models import IngestionAnalysisResult, ClipReviewResult
from utils.filenames import clean_filename, build_clip_filename
from utils.timestamps import natural_sort_key
from services.youtube_service import extract_youtube_id, fetch_latest_channel_vods
from services.transcript_service import get_formatted_transcript
from services.drive_service import get_or_create_stream_folder, get_all_filenames_in_drive_folder, upload_to_google_drive
from services.clip_service import slice_local_vod, write_metadata_text_file
from ui.components.clip_data_grid import ClipDataGrid
from ui.error_popup_window import ErrorPopupWindow
from ui.layout_manager_window import LayoutManagerWindow
from ui.batch_verification_window import BatchVerificationWindow

logger = logging.getLogger(__name__)

class ClipYT(ctk.CTk):
    def connect_to_google(self):
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = None
        if os.path.exists(config.token_cache_file):
            with open(config.token_cache_file, 'rb') as token:
                creds = pickle.load(token)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(config.client_secrets_file, scopes)
                creds = flow.run_local_server(port=0)
            with open(config.token_cache_file, 'wb') as token:
                pickle.dump(creds, token)

        self.client = gspread.authorize(creds)
        self.sheet = self.client.open(config.spreadsheet_name)
        self.drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)
        self.stream_list_tab = self.sheet.worksheet("Stream List")

    def show_error_popup(self, error_message):
        ErrorPopupWindow(self, error_message)

    def safe_update_status(self, text, color):
        self.after(0, lambda: self.status_var.set(text))
        self.after(0, lambda: self.status_label.configure(text_color=color))

    def safe_update_findclip_status(self, text, color):
        self.after(0, lambda: self.file_status_var.set(text))
        self.after(0, lambda: self.file_status_label.configure(text_color=color))

    def safe_update_batch_status(self, text, color):
        self.after(0, lambda: self.batch_status_var.set(text))
        self.after(0, lambda: self.batch_status_label.configure(text_color=color))

    def stop_loading_bar(self):
        self.batch_progress_bar.stop()
        self.batch_progress_bar.grid_remove()

    def finalize_batch_ui(self):
        self.is_batch_processing = False
        self.batch_btn.configure(state="normal", text="🎬 Process All Pending Clips")
        self.dropdown.configure(state="normal")
        if hasattr(self, 'source_file_exists') and self.source_file_exists:
            self.check_source_btn.configure(state="disabled")
        else:
            self.check_source_btn.configure(state="normal")
            
    def refresh_worksheet_dropdowns(self):
        self.stream_titles = self.stream_list_tab.col_values(1)[1:] 
        self.dropdown.configure(values=self.stream_titles, command=self.on_worksheet_selected)
        if self.stream_titles:
            self.dropdown.set(self.stream_titles[0])
            self.on_worksheet_selected(self.stream_titles[0])

    def on_worksheet_selected(self, choice):
        if self.is_batch_processing:
            self.show_error_popup("Batch Lock Error:\n\nCannot transition streams while queues run.")
            return
        self.active_choice = choice
        self.sort_states.clear() 
        self.active_broadcast_date = "" 
        self.executor.submit(self.load_stream_clips)

    def on_vod_dropdown_selected(self, selected_title_short):
        if not self.scraped_vod_options: return
        selected_idx = self.vod_select_dropdown._values.index(selected_title_short)
        target_vod = self.scraped_vod_options[selected_idx]

        self.new_stream_title.delete(0, tk.END)
        self.new_stream_date.delete(0, tk.END)
        self.new_stream_poster.delete(0, tk.END)
        self.new_stream_url.delete(0, tk.END)

        self.new_stream_title.insert(0, clean_filename(target_vod['title']))
        self.new_stream_date.insert(0, target_vod['date'])
        self.new_stream_poster.insert(0, target_vod['creator'])
        self.new_stream_url.insert(0, target_vod['url'])

    def open_layout_manager(self):
        if self.is_batch_processing: return
        LayoutManagerWindow(self, self.current_column_order, self.column_visibility, self.apply_new_column_order)

    def apply_new_column_order(self, reordered_list):
        self.current_column_order = reordered_list
        self.refresh_grid_view()

    def refresh_grid_view(self):
        """Prepares the drive cache data and passes it to the grid component."""
        if not hasattr(self, 'current_drive_cache') or not self.current_drive_cache:
            self.clip_grid.render_data_grid([])
            return

        formatted_data = []
        
        # Scenario A: The cache is a dictionary (e.g., {'Video Title': 'DriveID'})
        if isinstance(self.current_drive_cache, dict):
            for title in self.current_drive_cache.keys():
                formatted_data.append({
                    'title': title, 
                    'start_time': '--:--', 
                    'end_time': '--:--', 
                    'status': 'In Drive'
                })
                
        # Scenario B: The cache is a list of strings (e.g., ['Video 1', 'Video 2'])
        elif isinstance(self.current_drive_cache, list) and len(self.current_drive_cache) > 0 and isinstance(self.current_drive_cache[0], str):
            for title in self.current_drive_cache:
                formatted_data.append({
                    'title': title, 
                    'start_time': '--:--', 
                    'end_time': '--:--', 
                    'status': 'In Drive'
                })
                
        # Scenario C: It is already a list of dictionaries
        else:
            formatted_data = self.current_drive_cache
            
        # Send the properly packaged data to the grid!
        self.clip_grid.render_data_grid(formatted_data)

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

    def start_batch_process(self):
        self.is_batch_processing = True
        self.batch_btn.configure(state="disabled", text="⏳ Processing Batch Queue...")
        self.dropdown.configure(state="disabled")
        self.executor.submit(self.run_batch_worker)

    def start_channel_scan_thread(self):
        target_channel = self.channel_input_field.get().strip()
        if not target_channel:
            self.show_error_popup("Scan Error:\n\nPlease enter a valid channel handle or profile link URL.")
            return
            
        try:
            limit_val = int(self.channel_limit_field.get().strip())
        except ValueError:
            limit_val = 50 # Safe fallback if user typed letters
            
        self.scan_channel_btn.configure(state="disabled", text="⏳ Extracting Live VODs...")
        self.executor.submit(self.run_channel_scan_worker, target_channel, limit_val)
        
    def run_channel_scan_worker(self, channel, limit):
        try:
            self.scraped_vod_options = fetch_latest_channel_vods(channel, limit=limit)
            display_titles = [f"[{v['date']}] {v['title'][:40]}..." for v in self.scraped_vod_options]
            
            self.after(0, lambda: self.vod_select_dropdown.configure(values=display_titles))
            if display_titles:
                self.after(0, lambda: self.vod_select_dropdown.set(display_titles[0]))
                self.after(0, lambda: self.on_vod_dropdown_selected(display_titles[0]))
                # --- NEW: Enable the run button since VODs are loaded ---
                self.after(0, lambda: self.run_ai_btn.configure(state="normal"))
            else:
                # --- NEW: Keep disabled if the channel had 0 valid VODs ---
                self.after(0, lambda: self.run_ai_btn.configure(state="disabled"))
                
        except Exception as e:
            self.after(0, lambda e_val=e: self.show_error_popup(f"Scan Error:\n\n{str(e_val)}"))
            # Keep disabled if the scan crashes
            self.after(0, lambda: self.run_ai_btn.configure(state="disabled"))
        finally:
            self.after(0, lambda: self.scan_channel_btn.configure(state="normal", text="🔍 Fetch Recent Live VODs"))

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

        if not all([title, date, poster, url, count, min_sec, max_sec, scan_bef, scan_aft]):
            self.show_error_popup("Validation Error:\n\nAll parameters must be completely filled out for single VOD ingestion.")
            return

        self.run_ai_btn.configure(state="disabled", text="⏳ Running Pipeline Ingestion...")
        self.executor.submit(self.run_single_ai_ingestion, title, date, poster, url, count, min_sec, max_sec, scan_bef, scan_aft)

    def start_batch_range_thread(self):
        channel = self.batch_channel_field.get().strip()
        months_input = self.batch_range_field.get().strip()
        count = self.batch_clip_count.get().strip()
        min_sec = self.batch_min_sec.get().strip()
        max_sec = self.batch_max_sec.get().strip()

        if not all([channel, months_input, count, min_sec, max_sec]):
            self.show_error_popup("Validation Error:\n\nPlease specify all timeline automation entries completely.")
            return

        self.is_batch_processing = True
        self.run_batch_range_btn.configure(state="disabled", text="⏳ Scraping Channel (This may take a moment)...")

        self.batch_progress_bar.grid()
        self.batch_progress_bar.start()

        self.executor.submit(self._background_scrape_and_verify, channel, months_input, count, min_sec, max_sec)

    def _background_scrape_and_verify(self, channel, months_input, count, min_sec, max_sec):
        try:
            lookback_months = int(str(months_input).strip())
            today_date = dt_date(2026, 6, 24)
            start_threshold = today_date - relativedelta(months=lookback_months)
            
            all_scraped_vods = fetch_latest_channel_vods(channel, date_after=start_threshold, limit=0)
            target_batch = []
            
            for vod in all_scraped_vods:
                try:
                    vod_date = datetime.strptime(vod['date'], '%Y-%m-%d').date()
                    if start_threshold <= vod_date <= today_date:
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
                    verified_streams, count, min_sec, max_sec
                )
            ))
        except Exception as e:
            self.safe_update_batch_status("Scraping failed.", "#e74c3c")
            self.after(0, self.stop_loading_bar)
            self.after(0, lambda err=e: self.show_error_popup(f"Scrape Error:\n\n{str(err)}"))
            self.after(0, self.finalize_batch_ui)

    def execute_verified_batch_processing(self, verified_streams, count, min_sec, max_sec):
        if not verified_streams:
            self.finalize_batch_ui()
            return
            
        self.run_batch_range_btn.configure(state="disabled", text="⚙️ Running Batch Automation...")
        self.executor.submit(self.run_batch_range_ingestion, verified_streams, count, min_sec, max_sec)

    def start_single_clip_pipeline(self, local_vod_path, row, filename, target_folder_id):
        self.safe_update_status("Running single processing task...", "#3498db")
        self.executor.submit(self.execute_clip_pipeline, local_vod_path, row, filename, target_folder_id)

    def __init__(self):
        super().__init__()
        self.title("Local Stream Clipper Studio")
        self.geometry("1300x750")
        ctk.set_appearance_mode("dark")
        
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        self.raw_headers = []
        self.current_column_order = []
        self.current_clips_data = []
        self.column_visibility = {} 
        self.active_choice = None
        self.active_broadcast_date = "" 
        self.sort_states = {} 
        self.is_batch_processing = False  
        self.canvas_window = None
        self.scraped_vod_options = []
        self.source_file_exists = False
        
        self.current_local_vod = ""
        self.current_drive_cache = set()
        self.current_folder_id = ""
        
        self.cached_folder_ids = {}

        self.tab_control = ctk.CTkTabview(self)
        self.tab_control.pack(padx=10, pady=10, fill="both", expand=True)
        
        self.find_clip_tab = self.tab_control.add("Find Clips")
        self.studio_tab = self.tab_control.add("Make Clips")
        self.batch_tab = self.tab_control.add("Find & Make All Clips")

        self.setup_studio_ui()
        self.setup_find_clip_ui()
        self.setup_batch_range_ui()

        self.connect_to_google()
        self.ai_client = genai.Client(api_key=config.gemini_api_key)

        self.refresh_worksheet_dropdowns()

    def load_stream_clips(self):
        choice = self.active_choice
        if not choice: return
        try:
            self.safe_update_status(f"Fetching rows from tab '{choice}'...", "#3498db")
            
            all_streams_meta = self.stream_list_tab.get_all_records()
            for item in all_streams_meta:
                if str(item.get("Title", "")).strip() == choice.strip():
                    self.active_broadcast_date = str(item.get("Broadcast Date", item.get("Date", ""))).strip()
                    break

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

            safe_title = clean_filename(choice)
            expected_local_vod = os.path.join(config.input_vods_dir, f"{safe_title}.mp4")
            
            folder_key = f"{self.active_broadcast_date}_{choice}"
            if folder_key not in self.cached_folder_ids:
                self.cached_folder_ids[folder_key] = get_or_create_stream_folder(choice, self.active_broadcast_date, self.drive_service)
            
            target_folder_id = self.cached_folder_ids[folder_key]
            existing_files_cache = get_all_filenames_in_drive_folder(target_folder_id, self.drive_service)

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

            self.current_local_vod = expected_local_vod
            self.current_drive_cache = existing_files_cache
            self.current_folder_id = target_folder_id

            self.after(0, lambda: self.layout_btn.configure(state="normal"))
            self.after(0, self.refresh_grid_view)
            
        except Exception as e:
            self.after(0, lambda e_val=e: self.show_error_popup(f"Data Retrieval Exception:\n{str(e_val)}"))

    def setup_studio_ui(self):
        self.studio_tab.grid_columnconfigure(0, weight=1)
        self.studio_tab.grid_rowconfigure(2, weight=1)

        # 1. MUST BUILD THE WALL FIRST: Create the top_bar frame
        self.top_bar = ctk.CTkFrame(self.studio_tab) 
        self.top_bar.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew") # Adjust row/column if needed

        # 2. NOW HANG THE PICTURE: Add the label inside self.top_bar
        self.label = ctk.CTkLabel(self.top_bar, text="Select Active Stream Grid:", font=("Helvetica", 16, "bold"))
        self.label.grid(row=0, column=0, padx=10, pady=10) # Adjust grid settings as needed

        # 3. AND THEN ADD THE NEW GRID WE JUST MADE
        self.clip_grid = ClipDataGrid(self.studio_tab, width=900, height=500) 
        self.clip_grid.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="nsew")

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

        self.outer_container = ctk.CTkFrame(self.studio_tab, fg_color="#1d1d1d")
        self.outer_container.grid(row=2, column=0, padx=20, pady=15, sticky="nsew")
        self.outer_container.grid_columnconfigure(0, weight=1)
        self.outer_container.grid_rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(self.outer_container, bg="#1d1d1d", bd=0, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.v_scrollbar = ctk.CTkScrollbar(self.outer_container, orientation="vertical", command=self.canvas.yview)
        self.v_scrollbar.grid(row=0, column=1, sticky="ns")
        self.h_scrollbar = ctk.CTkScrollbar(self.outer_container, orientation="horizontal", command=self.canvas.xview)
        self.h_scrollbar.grid(row=1, column=0, sticky="ew")

        self.canvas.configure(xscrollcommand=self.h_scrollbar.set, yscrollcommand=self.v_scrollbar.set)
        self.table_content_frame = None

        self.status_var = tk.StringVar(value="Status: Ready")
        self.status_label = ctk.CTkLabel(self.studio_tab, textvariable=self.status_var, font=("Helvetica", 12, "italic"))
        self.status_label.grid(row=3, column=0, padx=20, pady=10, sticky="w")

    def setup_find_clip_ui(self):
        self.find_clip_tab.grid_columnconfigure(0, weight=1)

        channel_frame = ctk.CTkFrame(self.find_clip_tab)
        channel_frame.grid(row=0, column=0, padx=20, pady=(15, 5), sticky="ew")
        
        # --- MAGIC LAYOUT FIX ---
        # Make the URL text box column expand, pushing the right side flush to the edge
        channel_frame.grid_columnconfigure(1, weight=1)

        # --- ROW 0: The Fetching Controls ---
        ctk.CTkLabel(channel_frame, text="Scan Channel Handle / URL:", font=("Helvetica", 12, "bold")).grid(row=0, column=0, padx=15, pady=(15, 5), sticky="e")
        
        self.channel_input_field = ctk.CTkEntry(channel_frame, placeholder_text="e.g., @SpacesAreEvil or channel URL link")
        # Set sticky="ew" so the text box stretches dynamically to fill the empty space
        self.channel_input_field.grid(row=0, column=1, padx=5, pady=(15, 5), sticky="ew")
        self.channel_input_field.insert(0, "@SpacesAreEvil")

        ctk.CTkLabel(channel_frame, text="Max VODs:", font=("Helvetica", 11, "bold")).grid(row=0, column=2, padx=(10, 2), pady=(15, 5), sticky="e")
        self.channel_limit_field = ctk.CTkEntry(channel_frame, width=50)
        self.channel_limit_field.insert(0, "50")
        self.channel_limit_field.grid(row=0, column=3, padx=(0, 10), pady=(15, 5), sticky="w")

        self.scan_channel_btn = ctk.CTkButton(channel_frame, text="🔍 Fetch Recent Broadcast VODs", command=self.start_channel_scan_thread)
        # Anchor the button to the East edge
        self.scan_channel_btn.grid(row=0, column=4, padx=(0, 5), pady=(15, 5), sticky="e") 

        # --- ROW 1: The Selection Dropdown ---
        ctk.CTkLabel(channel_frame, text="Select Target Video:", font=("Helvetica", 11, "bold")).grid(row=1, column=0, padx=15, pady=(15, 5), sticky="w")
        
        self.vod_select_dropdown = ctk.CTkOptionMenu(channel_frame, values=["Scan channel first..."], width=450, command=self.on_vod_dropdown_selected)
        # Span the dropdown across the 3 right-most columns, and stick it to the East edge
        self.vod_select_dropdown.grid(row=1, column=1, columnspan=4, padx=5, pady=(15, 5), sticky="ew")

        meta_frame = ctk.CTkFrame(self.find_clip_tab)
        meta_frame.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        
        ctk.CTkLabel(meta_frame, text="Stream Title:", font=("Helvetica", 11, "bold")).grid(row=0, column=0, padx=15, pady=10, sticky="e")
        self.new_stream_title = ctk.CTkEntry(meta_frame, placeholder_text="Worksheet Tab Name", width=250)
        self.new_stream_title.grid(row=0, column=1, padx=5, pady=10, sticky="w")

        ctk.CTkLabel(meta_frame, text="Broadcast Date:", font=("Helvetica", 11, "bold")).grid(row=0, column=2, padx=10, pady=5, sticky="e")
        self.new_stream_date = ctk.CTkEntry(meta_frame, placeholder_text="YYYY-MM-DD", width=140)
        self.new_stream_date.grid(row=0, column=3, padx=5, pady=5, sticky="w")

        ctk.CTkLabel(meta_frame, text="Posted By Creator:", font=("Helvetica", 11, "bold")).grid(row=0, column=4, padx=10, pady=5, sticky="e")
        self.new_stream_poster = ctk.CTkEntry(meta_frame, width=150)
        self.new_stream_poster.grid(row=0, column=5, padx=5, pady=5, sticky="w")

        ctk.CTkLabel(meta_frame, text="YouTube URL Link:", font=("Helvetica", 11, "bold")).grid(row=1, column=0, padx=10, pady=5, sticky="e")
        self.new_stream_url = ctk.CTkEntry(meta_frame, placeholder_text="https://www.youtube.com/watch?v=...", width=250)
        self.new_stream_url.grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky="ew")

        ctk.CTkLabel(meta_frame, text="Target Clip Count:", font=("Helvetica", 11, "bold")).grid(row=1, column=3, padx=10, pady=5, sticky="e")
        self.param_clip_count = ctk.CTkEntry(meta_frame, width=60)
        self.param_clip_count.insert(0, "10")
        self.param_clip_count.grid(row=1, column=4, padx=5, pady=5, sticky="w")

        ctk.CTkLabel(meta_frame, text="Clip Size Limits (Sec):", font=("Helvetica", 11, "bold")).grid(row=2, column=0, padx=10, pady=5, sticky="e")
        size_bounds_frame = ctk.CTkFrame(meta_frame, fg_color="transparent")
        size_bounds_frame.grid(row=2, column=1, sticky="w")
        
        self.param_min_sec = ctk.CTkEntry(size_bounds_frame, width=50)
        self.param_min_sec.insert(0, "60")
        self.param_min_sec.pack(side="left")
        ctk.CTkLabel(size_bounds_frame, text=" Min  /  Max ").pack(side="left", padx=5)
        self.param_max_sec = ctk.CTkEntry(size_bounds_frame, width=50)
        self.param_max_sec.insert(0, "180")
        self.param_max_sec.pack(side="left")

        ctk.CTkLabel(meta_frame, text="Context Window Scan (Sec):", font=("Helvetica", 11, "bold")).grid(row=2, column=2, padx=10, pady=5, sticky="e")
        scan_bounds_frame = ctk.CTkFrame(meta_frame, fg_color="transparent")
        scan_bounds_frame.grid(row=2, column=3, columnspan=3, sticky="w")
        
        self.param_scan_before = ctk.CTkEntry(scan_bounds_frame, width=50)
        self.param_scan_before.insert(0, "60")
        self.param_scan_before.pack(side="left")
        ctk.CTkLabel(scan_bounds_frame, text=" Before  /  After ").pack(side="left", padx=5)
        self.param_scan_after = ctk.CTkEntry(scan_bounds_frame, width=50)
        self.param_scan_after.insert(0, "60")
        self.param_scan_after.pack(side="left")

        self.run_ai_btn = ctk.CTkButton(self.find_clip_tab, text="🎬 Find clips from YouTube VOD and save to Google Sheets", fg_color="#2ecc71", hover_color="#27ae60", height=45, state="disabled", command=self.start_ai_ingestion_thread)
        self.run_ai_btn.grid(row=2, column=0, padx=20, pady=20, sticky="ew")

        self._ = tk.StringVar(value="Status: Waiting for YouTube Channel Name or URL")
        self.filestatus_label = ctk.CTkLabel(self.find_clip_tab, textvariable=self._, font=("Helvetica", 12, "italic"))
        self.filestatus_label.grid(row=3, column=0, padx=20, pady=5, sticky="w")

    def setup_batch_range_ui(self):
        self.batch_tab.grid_columnconfigure(0, weight=1)

        info_box = ctk.CTkFrame(self.batch_tab)
        info_box.grid(row=0, column=0, padx=20, pady=15, sticky="ew")
        
        lbl = ctk.CTkLabel(info_box, text="Batch Make Clips Automation Studio", font=("Helvetica", 16, "bold"), text_color="#3498db")
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

        self.run_batch_range_btn = ctk.CTkButton(self.batch_tab, text="🚀 Find & Make All Clips", fg_color="#3498db", hover_color="#2980b9", height=45, command=self.start_batch_range_thread)
        self.run_batch_range_btn.grid(row=2, column=0, padx=20, pady=25, sticky="ew")

        self.batch_status_var = tk.StringVar(value="Batch Status: System idle. Ready to query timeline ranges.")
        self.batch_status_label = ctk.CTkLabel(self.batch_tab, textvariable=self.batch_status_var, font=("Helvetica", 12, "italic"))
        self.batch_status_label.grid(row=3, column=0, padx=20, pady=5, sticky="w")

        self.batch_progress_bar = ctk.CTkProgressBar(self.batch_tab, mode="indeterminate", width=300)
        self.batch_progress_bar.grid(row=4, column=0, padx=20, pady=5, sticky="w")
        self.batch_progress_bar.set(0)
        self.batch_progress_bar.grid_remove() 

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
                pending_clips.append((row, filename))

        total_count = len(pending_clips)
        logger.info(f"[BATCH WORKER] Verification complete. Found {total_count} pending items to render.")
        
        if total_count == 0:
            self.safe_update_status("Batch Complete: All items up to date.", "#2ecc71")
            self.after(0, self.finalize_batch_ui)
            return

        for sequence_idx, (row, filename) in enumerate(pending_clips, start=1):
            start = str(row.get("Timestamp Start", ""))
            end = str(row.get("Timestamp End", ""))
            
            local_input_path = os.path.abspath(config.input_vods_dir)
            local_staging_path = os.path.abspath(os.path.join(config.output_vods_dir, filename))
            local_txt_path = os.path.abspath(os.path.join(config.output_vods_dir, filename.replace(".mp4", ".txt")))
            txt_filename = filename.replace(".mp4", ".txt")
            
            try:
                logger.info(f"Executing manual cut for {filename}")
                slice_local_vod(local_input_path, start, end, local_staging_path)
                
                # --- AGENTIC QA INJECTION ---
                if self.enable_qa_var.get() == "on":
                    self.safe_update_status("Running Agentic QA Review...", "#9b59b6")
                    review_data = self._agentic_clip_review(local_staging_path, row)
                    if review_data:
                        row["QA Grade"] = review_data.get("grade")
                        row["QA Visual Description"] = review_data.get("visual_description")
                        row["QA Is Match"] = review_data.get("is_match")
                        row["QA Feedback"] = review_data.get("feedback")
                        
                        if not review_data.get("is_match"):
                            filename = f"[QA_FAIL]_{filename}"
                            txt_filename = f"[QA_FAIL]_{txt_filename}"
                # ---------------------------

                write_metadata_text_file(row, local_txt_path)
                
                logger.info("Uploading asset data to Drive...")
                self.safe_update_status("Uploading to Drive...", "#3498db")
                upload_to_google_drive(local_staging_path, filename, 'video/mp4', target_folder_id, self.drive_service)
                upload_to_google_drive(local_txt_path, txt_filename, 'text/plain', target_folder_id, self.drive_service)
                
            except Exception as row_err:
                logger.error(f"[BATCH WORKER] Task error on item {filename}: {str(row_err)}")
                self.after(0, lambda f=filename, e=row_err: self.show_error_popup(f"Batch Exception on Item {f}:\n\n{str(e)}"))
            finally:
                for temp_file in (local_staging_path, local_txt_path):
                    if os.path.exists(temp_file):
                        try:
                            os.remove(temp_file)
                        except OSError as e:
                            logger.warning(f"[CLEANUP WARNING] Could not remove temp file {temp_file}: {e}")

        self.safe_update_status("Batch Success!", "#2ecc71")
        self.after(0, self.finalize_batch_ui)

    def run_single_ai_ingestion(self, title, date, poster, url, count, min_sec, max_sec, scan_bef, scan_aft):
        try:
            logger.info(f"[GEMINI PIPELINE] Initializing single pass ingestion for: '{title}'")
            video_id = extract_youtube_id(url)
            if not video_id:
                raise ValueError("Could not parse a valid YouTube video ID from link.")

            self.safe_update_findclip_status("Extracting stream captions...", "#3498db")
            transcript_payload = get_formatted_transcript(video_id)

            self.safe_update_findclip_status("Analyzing retention with Gemini...", "#3498db")
            clip_rows = self._query_gemini_strategist(transcript_payload, title, poster, url, count, min_sec, max_sec, scan_bef, scan_aft)

            if not clip_rows:
                raise ValueError("Gemini complete but zero clips matched parameters.")

            self.safe_update_findclip_status("Syncing workspace structures...", "#e67e22")
            self._commit_clips_to_spreadsheet(title, date, url, clip_rows)
            
            self.safe_update_findclip_status("Success! Stream ingested.", "#2ecc71")
            self.after(0, lambda: self.new_stream_title.delete(0, tk.END))
            self.after(0, lambda: self.new_stream_url.delete(0, tk.END))
            self.after(0, self.refresh_worksheet_dropdowns)

        except Exception as ai_err:
            logger.error(f"[GEMINI PIPELINE CRITICAL] Ingestion failed: {str(ai_err)}")
            self.safe_update_findclip_status("Ingestion Pipeline Crash.", "#e74c3c")
            self.after(0, lambda e=ai_err: self.show_error_popup(f"AI Ingestion Pipeline Crash:\n\n{str(e)}"))
        finally:
            self.after(0, lambda: self.run_ai_btn.configure(state="normal", text="🎬 Find clips from YouTube VOD and save to Google Sheets"))

    def run_batch_range_ingestion(self, verified_batch, count, min_sec, max_sec):
        try:
            total_batch_count = len(verified_batch)
            logger.info(f"[BATCH PIPELINE] Processing {total_batch_count} verified long-form vertical assets.")
            
            for batch_idx, current_vod in enumerate(verified_batch, start=1):
                vod_title = clean_filename(current_vod['title'])
                vod_date_str = current_vod['date']
                vod_url = current_vod['url']
                vod_creator = current_vod['creator']
                
                if vod_title in self.stream_titles:
                    logger.info(f"[BATCH PIPELINE] Skipping '{vod_title}' — already exists in Stream List.")
                    self.safe_update_batch_status(f"Skipping [{batch_idx}/{total_batch_count}]: '{vod_title[:20]}...' (Already Processed)", "#e67e22")
                    continue
                
                logger.info(f"[BATCH PIPELINE] [{batch_idx}/{total_batch_count}]: Ingesting video asset '{vod_title}'")
                self.safe_update_batch_status(f"Batch Ingest [{batch_idx}/{total_batch_count}]: Subtitles for '{vod_title[:15]}...'...", "#3498db")
                
                video_id = extract_youtube_id(vod_url)
                if not video_id: continue

                try:
                    transcript_payload = get_formatted_transcript(video_id)
                except Exception as tx_err:
                    logger.error(f"[BATCH PIPELINE] Skipping VOD '{vod_title}' — Subtitle tracks not found: {str(tx_err)}")
                    continue

                self.safe_update_batch_status(f"Batch Ingest [{batch_idx}/{total_batch_count}]: Running Gemini analysis...", "#3498db")
                clip_rows = self._query_gemini_strategist(transcript_payload, vod_title, vod_creator, vod_url, count, min_sec, max_sec, "60", "60")

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

    def _agentic_clip_review(self, local_staging_path, row):
        title = row.get("Title", "")
        desc = row.get("Description", "")
        notes = row.get("Editing Notes", "")
        
        logger.info(f"[QA REVIEW] Uploading {local_staging_path} to Gemini for visual analysis...")
        video_file = self.ai_client.files.upload(file=local_staging_path)
        
        try:
            # Poll Google until the video is fully processed and ready for analysis
            while not video_file.state or video_file.state.name != "ACTIVE":
                if video_file.state and video_file.state.name == "FAILED":
                    raise RuntimeError("Gemini failed to process the video file.")
                time.sleep(3)
                video_file = self.ai_client.files.get(name=video_file.name)
            
            system_instruction = (
                "You are an expert video Quality Assurance reviewer. Watch the provided video clip. "
                "Compare its actual visual and audio content against the expected metadata and intended viral moment. "
                "Determine if the clip correctly captures the intended subject matter."
            )
            
            user_prompt = (
                f"Expected Title: {title}\n"
                f"Expected Description: {desc}\n"
                f"Editing Notes / Intended Moment: {notes}\n\n"
                "Review the attached video. Does it accurately reflect this metadata? Describe what actually happens visually."
            )
            
            logger.info("[QA REVIEW] Video active. Requesting agentic review from Gemini...")
            response = self.ai_client.models.generate_content(
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
            return review_data
            
        except Exception as e:
            logger.error(f"[QA REVIEW ERROR] {str(e)}")
            return None
            
        finally:
            logger.info("[QA REVIEW] Cleaning up remote video file from Gemini servers.")
            try:
                self.ai_client.files.delete(name=video_file.name)
            except Exception as e:
                logger.warning(f"[QA REVIEW] Could not delete remote file: {e}")

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

    def execute_clip_pipeline(self, row, filename, target_folder_id):
        start = str(row.get("Timestamp Start", ""))
        end = str(row.get("Timestamp End", ""))
        vod_filename = os.path.abspath(os.path.join(config.output_vods_dir, filename))
        txt_filename = os.path.abspath(os.path.join(config.output_vods_dir, filename.replace(".mp4", ".txt")))
        txt_filename = txt_filename.replace(".mp4", ".txt")
        
        try:
            logger.info(f"Executing manual cut for {filename}")
            slice_local_vod(config.input_vods_dir, start, end, vod_filename)
            
            # --- AGENTIC QA INJECTION ---
            if self.enable_qa_var.get() == "on":
                self.safe_update_status("Running Agentic QA Review...", "#9b59b6")
                review_data = self._agentic_clip_review(vod_filename, row)
                if review_data:
                    row["QA Grade"] = review_data.get("grade")
                    row["QA Visual Description"] = review_data.get("visual_description")
                    row["QA Is Match"] = review_data.get("is_match")
                    row["QA Feedback"] = review_data.get("feedback")
                    
                    if not review_data.get("is_match"):
                        filename = f"[QA_FAIL]_{filename}"
                        txt_filename = f"[QA_FAIL]_{txt_filename}"
            # ---------------------------

            write_metadata_text_file(row, local_txt_path)
            
            logger.info("Uploading asset data to Drive...")
            self.safe_update_status("Uploading to Drive...", "#3498db")
            upload_to_google_drive(local_staging_path, filename, 'video/mp4', target_folder_id, self.drive_service)
            upload_to_google_drive(local_txt_path, txt_filename, 'text/plain', target_folder_id, self.drive_service)
                
            self.safe_update_status("Success!", "#2ecc71")
            
            self.current_drive_cache.add(filename)
            self.current_drive_cache.add(txt_filename)
            self.after(0, self.refresh_grid_view)
            
        except Exception as err:
            logger.error(f"Pipeline error: {str(err)}")
            self.safe_update_status("Pipeline Failure.", "#e74c3c")
            self.after(0, lambda e=err: self.show_error_popup(f"Pipeline Breakdown:\n\n{str(e)}"))
            
        finally:
            for temp_file in (local_staging_path, local_txt_path):
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except OSError as e:
                        logger.warning(f"[CLEANUP WARNING] Could not remove temp file {temp_file}: {e}")