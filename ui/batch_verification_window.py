import customtkinter as ctk

class BatchVerificationWindow(ctk.CTkToplevel):
    def __init__(self, parent, discovered_streams, existing_titles, on_confirm_callback):
        super().__init__(parent)
        self.title("Verify Streams for Processing")
        self.geometry("600x500")
        self.transient(parent)
        self.grab_set()
        
        self.on_confirm_callback = on_confirm_callback
        self.stream_checkboxes = []
        
        title_lbl = ctk.CTkLabel(
            self, 
            text="Select Streams to Ingest & Analyze", 
            font=ctk.CTkFont(size=16, weight="bold")
        )
        title_lbl.pack(pady=15)
        
        self.scroll_frame = ctk.CTkScrollableFrame(self, width=540, height=330)
        self.scroll_frame.pack(padx=20, pady=5, fill="both", expand=True)
        
        for stream in discovered_streams:
            title = stream.get('title', 'Unknown Title')
            date_str = stream.get('date', '')
            
            already_exists = title in existing_titles
            
            display_text = f"[{date_str}] {title}"
            if already_exists:
                display_text += " ⚠️ (In Workbook)"
                
            var = ctk.StringVar(value="off" if already_exists else "on")
            
            cb = ctk.CTkCheckBox(
                self.scroll_frame, 
                text=display_text,
                variable=var,
                onvalue="on",
                offvalue="off"
            )
            cb.pack(anchor="w", pady=6, padx=10)
            
            self.stream_checkboxes.append((cb, var, stream))
            
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=15, fill="x", padx=20)
        
        cancel_btn = ctk.CTkButton(btn_frame, text="Cancel", fg_color="#e74c3c", hover_color="#c0392b", command=self.destroy)
        cancel_btn.pack(side="left", padx=10, expand=True, fill="x")
        
        confirm_btn = ctk.CTkButton(btn_frame, text="Confirm & Process", fg_color="#2ecc71", hover_color="#27ae60", command=self.confirm_selection)
        confirm_btn.pack(side="right", padx=10, expand=True, fill="x")

    def confirm_selection(self):
        selected_streams = []
        for cb, var, stream in self.stream_checkboxes:
            if var.get() == "on":
                selected_streams.append(stream)
                
        self.destroy()
        self.on_confirm_callback(selected_streams)