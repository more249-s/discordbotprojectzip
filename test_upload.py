import os
import json
import asyncio
import requests
from config import Config
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

async def test_gofile():
    print("--- Testing Gofile ---")
    try:
        # Create a dummy file
        with open("test_dummy.txt", "w") as f:
            f.write("This is a test file for Gofile.")
        
        url = "https://upload.gofile.io/uploadfile"
        headers = {}
        if Config.GOFILE_TOKEN:
            headers["Authorization"] = f"Bearer {Config.GOFILE_TOKEN}"
        with open("test_dummy.txt", "rb") as f:
            files = {"file": f}
            resp = requests.post(url, files=files, headers=headers, timeout=60)
        
        print(f"Upload Resp Status: {resp.status_code}")
        print(f"Upload Resp Body: {resp.text}")
        
    except Exception as e:
        print(f"Gofile Exception: {e}")

async def test_gdrive():
    print("\n--- Testing Google Drive ---")
    try:
        # Create a dummy file
        with open("test_dummy_drive.txt", "w") as f:
            f.write("This is a test file for Google Drive.")
            
        if not Config.GOOGLE_SERVICE_ACCOUNT_JSON:
            print("Config.GOOGLE_SERVICE_ACCOUNT_JSON is EMPTY")
            return
        if not Config.GOOGLE_DRIVE_FOLDER_ID:
            print("Config.GOOGLE_DRIVE_FOLDER_ID is EMPTY")
            return

        print("Attempting to parse JSON...")
        # Try to fix potential newline issues in the private key string before parsing
        json_str = Config.GOOGLE_SERVICE_ACCOUNT_JSON
        # If it's wrapped in quotes by mistake or has escaped characters
        info = json.loads(json_str)
        
        # FIX: The private key in .env might have literal \n that need to be actual newlines
        if "private_key" in info:
            info["private_key"] = info["private_key"].replace("\\n", "\n")
            
        creds = service_account.Credentials.from_service_account_info(info)
        service = build('drive', 'v3', credentials=creds)
        
        file_metadata = {'name': 'test_dummy_drive.txt', 'parents': [Config.GOOGLE_DRIVE_FOLDER_ID]}
        media = MediaFileUpload('test_dummy_drive.txt', resumable=True)
        request = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink',
            supportsAllDrives=True
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"Upload progress: {int(status.progress() * 100)}%")
        
        service.permissions().create(
            fileId=response.get('id'),
            body={'type': 'anyone', 'role': 'viewer'},
            supportsAllDrives=True
        ).execute()

        print(f"Upload Success! ID: {response.get('id')}")
        print(f"Link: {response.get('webViewLink')}")
        
    except Exception as e:
        print(f"Google Drive Exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_gofile())
    asyncio.run(test_gdrive())
