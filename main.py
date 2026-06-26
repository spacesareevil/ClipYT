from config.settings import config
from utils.logging_utils import setup_logging
from ui.main_window import ClipYT

if __name__ == "__main__":
    setup_logging()
    
    # Fail fast if environment is misconfigured
    config.validate_startup()
    
    # Boot the application
    app = ClipYT()
    app.mainloop()