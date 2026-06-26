import logging
from googleapiclient.http import MediaFileUpload
from config.settings import config

logger = logging.getLogger(__name__)

def get_or_create_stream_folder(stream_title: str, broadcast_date: str, drive_service) -> str:
    full_folder_name = f"{str(broadcast_date).strip()} {stream_title.strip()}" if broadcast_date else stream_title.strip()
    safe_title = full_folder_name.replace("'", "\\'")
    
    query = f"'{config.master_drive_folder_id}' in parents and name = '{safe_title}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    
    logger.info(f"[DRIVE API] Checking for existing folder: '{full_folder_name}'")
    results = drive_service.files().list(q=query, fields="files(id)").execute()
    folders = results.get('files', [])
    
    if folders: 
        logger.info(f"[DRIVE API] Found existing Drive folder ID: {folders[0]['id']}")
        return folders[0]['id']
        
    logger.info(f"[DRIVE API] Creating new Drive folder: '{full_folder_name}'")
    folder_metadata = {
        'name': full_folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [config.master_drive_folder_id]
    }
    new_folder = drive_service.files().create(body=folder_metadata, fields='id').execute()
    return new_folder.get('id')

def get_all_filenames_in_drive_folder(folder_id: str, drive_service) -> set:
    logger.info(f"[DRIVE API] Caching Cloud Storage inventory map for folder ID: {folder_id}")
    query = f"'{folder_id}' in parents and trashed = false"
    
    filenames = set()
    page_token = None

    while True:
        results = drive_service.files().list(
            q=query, 
            fields="nextPageToken, files(name)", 
            pageSize=1000,
            pageToken=page_token
        ).execute()
        
        for f in results.get('files', []):
            filenames.add(f['name'])
            
        page_token = results.get('nextPageToken')
        if not page_token:
            break
            
    logger.info(f"[DRIVE API] Inventory scan complete. Found {len(filenames)} files.")
    return filenames

def upload_to_google_drive(local_file_path: str, filename: str, mime_type: str, target_folder_id: str, drive_service) -> str:
    logger.info(f"[DRIVE API] Initiating chunked upload for file: {filename}")
    file_metadata = {'name': filename, 'parents': [target_folder_id]}
    
    media = MediaFileUpload(local_file_path, mimetype=mime_type, resumable=True, chunksize=1024*1024)
    
    request = drive_service.files().create(body=file_metadata, media_body=media, fields='id')
    response = None
    
    while response is None:
        status, response = request.next_chunk()
        
    logger.info(f"[DRIVE API] Successfully uploaded {filename} (Drive ID: {response.get('id')})")
    return response.get('id')