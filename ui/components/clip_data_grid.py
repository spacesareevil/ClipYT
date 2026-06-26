import logging
import customtkinter as ctk

logger = logging.getLogger(__name__)

class ClipDataGrid(ctk.CTkScrollableFrame):
    def __init__(self, master, **kwargs):
        # We inherit from CTkScrollableFrame so the grid handles its own scrolling
        super().__init__(master, **kwargs)
        
        self.headers = ["Clip Title", "Start Time", "End Time", "Status", "Action"]
        self.current_data = []  # Will hold the list of dictionaries/lists for the rows
        
        # We store references to widgets so we can clear them out when re-rendering
        self.grid_widgets = []
        
        # State for column sorting
        self.sort_column_index = None
        self.sort_ascending = True
        
        # Tooltip state
        self.active_tooltip = None

    def clear_grid(self):
        """Destroys all current widgets in the grid to prepare for a fresh render."""
        for widget in self.grid_widgets:
            widget.destroy()
        self.grid_widgets.clear()
    
    def render_data_grid(self, clip_data):
        """Builds the headers and rows based on the provided clip data."""
        self.clear_grid()
        self.current_data = clip_data

        logger.debug(f"Entered render_data_grid. Contents of clip_data: {clip_data}")

        # 1. Handle Empty State
        if not clip_data:
            empty_label = ctk.CTkLabel(
                self, 
                text="No clip data available. Fetch and scan a VOD to begin.", 
                font=("Helvetica", 14, "italic"), 
                text_color="gray"
            )
            empty_label.grid(row=0, column=0, padx=20, pady=50)
            self.grid_widgets.append(empty_label)
            return
        
        logger.debug(f"Headers: {self.headers}")

        # 2. Render Headers
        for col_idx, header_text in enumerate(self.headers):
            header_lbl = ctk.CTkLabel(
                self, 
                text=header_text, 
                font=("Helvetica", 12, "bold"),
                cursor="hand2"  # Indicates it can be clicked for sorting later
            )
            header_lbl.grid(row=0, column=col_idx, padx=10, pady=(5, 10), sticky="w")
            self.grid_widgets.append(header_lbl)
            
            # We will bind the sorting click event in the next step
            header_lbl.bind("<Button-1>", lambda e, idx=col_idx: self.sort_column_data(idx))

        # 3. Render Data Rows
        for row_idx, clip in enumerate(clip_data, start=1):
            
            # Column 0: Title (Truncated for clean UI)
            title_text = str(clip.get('title', 'Untitled'))
            display_title = title_text if len(title_text) < 40 else title_text[:37] + "..."
            title_lbl = ctk.CTkLabel(self, text=display_title, anchor="w", width=250)
            title_lbl.grid(row=row_idx, column=0, padx=10, pady=4, sticky="w")
            self.grid_widgets.append(title_lbl)

            # Column 1: Start Time
            start_lbl = ctk.CTkLabel(self, text=str(clip.get('start_time', '00:00:00')))
            start_lbl.grid(row=row_idx, column=1, padx=10, pady=4, sticky="w")
            self.grid_widgets.append(start_lbl)

            # Column 2: End Time
            end_lbl = ctk.CTkLabel(self, text=str(clip.get('end_time', '00:00:00')))
            end_lbl.grid(row=row_idx, column=2, padx=10, pady=4, sticky="w")
            self.grid_widgets.append(end_lbl)

            # Column 3: Status
            status_text = str(clip.get('status', 'Pending'))
            status_color = "#2ecc71" if status_text.lower() == "complete" else ("#f1c40f" if status_text.lower() == "processing" else "#ecf0f1")
            status_lbl = ctk.CTkLabel(self, text=status_text, text_color=status_color)
            status_lbl.grid(row=row_idx, column=3, padx=10, pady=4, sticky="w")
            self.grid_widgets.append(status_lbl)

            # Column 4: Action Button (e.g., delete row)
            action_btn = ctk.CTkButton(
                self, 
                text="Discard", 
                width=60, 
                fg_color="#e74c3c", 
                hover_color="#c0392b"
            )
            action_btn.grid(row=row_idx, column=4, padx=10, pady=4, sticky="w")
            self.grid_widgets.append(action_btn)

    def sort_column_data(self, col_index):
        """Sorts the grid data based on the clicked column header."""
        if not self.current_data:
            return

        # Toggle sort direction if clicking the same column, else default to Ascending
        if self.sort_column_index == col_index:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_column_index = col_index
            self.sort_ascending = True

        # Define keys matching the column indexes
        # Headers: ["Clip Title", "Start Time", "End Time", "Status", "Action"]
        keys = ["title", "start_time", "end_time", "status", None]
        sort_key = keys[col_index]

        if sort_key:
            # Sort the list of dictionaries
            self.current_data.sort(
                key=lambda x: str(x.get(sort_key, '')).lower(),
                reverse=not self.sort_ascending
            )
            
            # Re-render the grid with the newly sorted data
            self.render_data_grid(self.current_data)

    def _show_cell_tooltip(self, event, text):
        """Creates a floating tooltip when hovering over truncated text."""
        if self.active_tooltip:
            self._hide_cell_tooltip(None)
        
        # Calculate position based on the mouse event
        x = event.widget.winfo_rootx() + 25
        y = event.widget.winfo_rooty() + 25
        
        self.active_tooltip = ctk.CTkToplevel(self)
        self.active_tooltip.wm_overrideredirect(True)
        self.active_tooltip.wm_geometry(f"+{x}+{y}")
        
        label = ctk.CTkLabel(
            self.active_tooltip, 
            text=text, 
            fg_color="#333333", 
            text_color="white",
            corner_radius=6, 
            padx=10, 
            pady=5
        )
        label.pack()

    def _hide_cell_tooltip(self, event):
        """Destroys the active tooltip."""
        if self.active_tooltip:
            self.active_tooltip.destroy()
            self.active_tooltip = None