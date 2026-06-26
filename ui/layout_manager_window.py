import json
import logging
import tkinter as tk
import customtkinter as ctk
from config.settings import config

logger = logging.getLogger(__name__)

class LayoutManagerWindow(ctk.CTkToplevel):
    def __init__(self, master, current_order, visible_dict, apply_callback):
        super().__init__(master)
        self.title("Manage Table Layout & Visibility")
        self.geometry("400x500")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        
        self.apply_callback = apply_callback
        self.visible_dict = visible_dict
        self.working_order = list(current_order)

        lbl = ctk.CTkLabel(self, text="Configure Columns (Drag items or toggle selection):", font=("Helvetica", 13, "bold"))
        lbl.pack(padx=20, pady=(15, 5), anchor="w")

        self.list_frame = ctk.CTkFrame(self)
        self.list_frame.pack(padx=20, pady=5, fill="both", expand=True)

        self.listbox = tk.Listbox(
            self.list_frame, bg="#2b2b2b", fg="#ffffff", selectbackground="#3498db", 
            font=("Helvetica", 11), bd=0, highlightthickness=0, activestyle="none"
        )
        self.listbox.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        self.refresh_listbox_view()

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(padx=20, pady=5, fill="x")

        self.up_btn = ctk.CTkButton(btn_frame, text="▲ Move Up", width=100, command=self.move_item_up)
        self.up_btn.pack(side="left", padx=5)

        self.down_btn = ctk.CTkButton(btn_frame, text="▼ Move Down", width=100, command=self.move_item_down)
        self.down_btn.pack(side="left", padx=5)

        self.toggle_btn = ctk.CTkButton(btn_frame, text="👁 Toggle Hide/Show", width=140, fg_color="#2c3e50", command=self.toggle_item_visibility)
        self.toggle_btn.pack(side="right", padx=5)

        apply_btn = ctk.CTkButton(self, text="Apply Changes to Grid", fg_color="#2ecc71", hover_color="#27ae60", command=self.save_and_apply)
        apply_btn.pack(padx=20, pady=15, fill="x")

    def refresh_listbox_view(self):
        self.listbox.delete(0, tk.END)
        for col in self.working_order:
            status = "[👁] " if self.visible_dict.get(col, True) else "[❌] "
            self.listbox.insert(tk.END, f"{status}{col}")

    def toggle_item_visibility(self):
        selected = self.listbox.curselection()
        if not selected: return
        idx = selected[0]
        col_name = self.working_order[idx]
        self.visible_dict[col_name] = not self.visible_dict.get(col_name, True)
        self.refresh_listbox_view()
        self.listbox.select_set(idx)

    def move_item_up(self):
        selected = self.listbox.curselection()
        if not selected or selected[0] == 0: return
        idx = selected[0]
        self.working_order[idx], self.working_order[idx-1] = self.working_order[idx-1], self.working_order[idx]
        self.refresh_listbox_view()
        self.listbox.select_set(idx - 1)

    def move_item_down(self):
        selected = self.listbox.curselection()
        if not selected or selected[0] == len(self.working_order) - 1: return
        idx = selected[0]
        self.working_order[idx], self.working_order[idx+1] = self.working_order[idx+1], self.working_order[idx]
        self.refresh_listbox_view()
        self.listbox.select_set(idx + 1)

    def save_and_apply(self):
        config_payload = {
            "column_order": self.working_order,
            "column_visibility": self.visible_dict
        }
        try:
            with open(config.layout_cache_file, "w", encoding="utf-8") as f:
                json.dump(config_payload, f, indent=4)
            logger.info("[LAYOUT] Custom column configuration successfully written to layout_config.json")
        except Exception as e:
            logger.error(f"[LAYOUT CRITICAL] Failed to write preferences to file: {str(e)}")

        self.apply_callback(self.working_order)
        self.destroy()