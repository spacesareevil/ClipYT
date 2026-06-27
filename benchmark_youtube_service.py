import time
from services.youtube_service import fetch_latest_channel_vods

start = time.time()
try:
    # Limit to 5 to avoid taking too long for baseline
    vods = fetch_latest_channel_vods("https://www.youtube.com/@mkbhd", limit=5)
    print(f"Found {len(vods)} vods")
except Exception as e:
    print(f"Error: {e}")
end = time.time()

print(f"Post-optimization time: {end - start:.2f} seconds")
