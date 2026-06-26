import customtkinter as ctk

class ErrorPopupWindow(ctk.CTkToplevel):
    def __init__(self, master, error_message):
        super().__init__(master)
        self.title("System Log Notification")
        self.geometry("600x400")
        self.attributes("-topmost", True)  
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.textbox = ctk.CTkTextbox(self, font=("Consolas", 11), wrap="word")
        self.textbox.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self.textbox.insert("0.0", error_message)
        self.textbox.configure(state="disabled")  

        self.close_btn = ctk.CTkButton(self, text="Dismiss", width=100, command=self.destroy)
        self.close_btn.grid(row=1, column=0, padx=20, pady=(0, 20))