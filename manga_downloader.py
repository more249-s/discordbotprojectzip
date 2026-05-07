import os
import zipfile
import requests
import cloudscraper
import aiohttp
from bs4 import BeautifulSoup
import uuid
import shutil
import asyncio
import json
import time
from config import Config
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from providers.manager import ProviderManager
from smart_stitch import smart_stitch_from_zip

class MangaDownloader:
    def __init__(self):
        self.provider_manager = ProviderManager()
        self.scraper = self.provider_manager.generic.scraper
        self.temp_dir = "temp_downloads"
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)

    @staticmethod
    def create_progress_bar(current, total, length=15, style="modern"):
        styles = {
            "modern": ("▰", "▱", "", ""),
            "dots": ("●", "○", "", ""),
            "square": ("■", "□", "", ""),
            "classic": ("#", "-", "[", "]"),
        }
        fill_char, empty_char, prefix, suffix = styles.get(style, styles["modern"])

        if total <= 0:
            return f"{prefix}{empty_char * length}{suffix} 0%"
        percent = max(0.0, min(1.0, float(current) / float(total)))
        filled = int(round(percent * length))
        bar = (fill_char * filled) + (empty_char * (length - filled))
        return f"{prefix}{bar}{suffix} {int(round(percent * 100))}%"

    async def download_chapter(self, url: str, chapter_title: str, progress_callback=None, **kwargs):
        """
        تحميل صور الفصل وضغطها في ملف ZIP.
        """
        loop = asyncio.get_event_loop()
        
        img_urls = await self.provider_manager.get_images(url)
        if not img_urls:
            return None

        # Create unique folder
        job_id = str(uuid.uuid4())[:8]
        job_dir = os.path.join(self.temp_dir, job_id)
        os.makedirs(job_dir)

        downloaded_files = []
        completed = 0
        
        def download_single_image(idx, img_url):
            try:
                headers = {"Referer": url, "User-Agent": "Mozilla/5.0"}
                r = self.scraper.get(img_url, stream=True, timeout=30, headers=headers)
                if r.status_code == 200:
                    ext = img_url.split('.')[-1].split('?')[0]
                    if len(ext) > 4 or "/" in ext:
                        ext = 'jpg'
                    filename = f"{idx:03d}.{ext}"
                    filepath = os.path.join(job_dir, filename)
                    with open(filepath, 'wb') as f:
                        for chunk in r.iter_content(1024 * 64):
                            if chunk:
                                f.write(chunk)
                    return filepath
            except Exception as e:
                print(f"Image download failed ({idx}): {e}")
                pass
            return None

        semaphore = asyncio.Semaphore(8)

        async def download_with_limit(idx, img_url):
            async with semaphore:
                return await loop.run_in_executor(None, download_single_image, idx, img_url)

        tasks = [download_with_limit(i, img_url) for i, img_url in enumerate(img_urls)]
        for task in asyncio.as_completed(tasks):
            filepath = await task
            if filepath:
                downloaded_files.append(filepath)
            completed += 1
            if progress_callback:
                if completed % 2 == 0 or completed == len(img_urls):
                    await progress_callback(completed, len(img_urls), "تحميل الصور")

        if not downloaded_files:
            shutil.rmtree(job_dir)
            return None

        downloaded_files.sort()
        zip_name = f"{chapter_title.replace(' ', '_')}_{job_id}.zip"
        final_path = os.path.join(self.temp_dir, zip_name)
        with zipfile.ZipFile(final_path, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
            for file in downloaded_files:
                zipf.write(file, os.path.basename(file))

        # Cleanup folder
        shutil.rmtree(job_dir)
        
        return final_path

    async def upload_to_gofile(self, file_path: str, progress_callback=None):
        """
        رفع الملف إلى Gofile مع محاولات إعادة المحاولة.
        """
        async def upload():
            try:
                if progress_callback:
                    await progress_callback(0, 100, "رفع الملف إلى Gofile")

                upload_url = "https://upload.gofile.io/uploadfile"
                boundary = f"----CatBiBoundary{uuid.uuid4().hex}"
                filename = os.path.basename(file_path)
                file_size = os.path.getsize(file_path)
                head = (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                    "Content-Type: application/zip\r\n\r\n"
                ).encode("utf-8")
                tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
                total_size = len(head) + file_size + len(tail)
                uploaded = 0
                last_update = 0.0

                async def body_generator():
                    nonlocal uploaded, last_update
                    uploaded += len(head)
                    yield head

                    with open(file_path, "rb") as f:
                        while True:
                            chunk = f.read(1024 * 1024)
                            if not chunk:
                                break
                            uploaded += len(chunk)
                            now = time.monotonic()
                            if progress_callback and (now - last_update >= 1.5 or uploaded >= total_size):
                                last_update = now
                                percent = min(99, int(uploaded * 100 / total_size))
                                await progress_callback(percent, 100, "رفع الملف إلى Gofile")
                            yield chunk

                    uploaded += len(tail)
                    yield tail

                headers = {
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(total_size),
                }
                if Config.GOFILE_TOKEN:
                    headers["Authorization"] = f"Bearer {Config.GOFILE_TOKEN}"

                timeout = aiohttp.ClientTimeout(total=900)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(upload_url, data=body_generator(), headers=headers) as resp:
                        text = await resp.text()
                        if resp.status == 200:
                            payload = json.loads(text)
                            resp_data = payload.get("data", {})
                            if progress_callback:
                                await progress_callback(100, 100, "رفع الملف إلى Gofile")
                            if payload.get("status") in ("ok", True):
                                return resp_data.get("downloadPage") or resp_data.get("pageLink") or resp_data.get("directLink")
                            print(f"Gofile upload returned error payload: {text[:300]}")
                            return None

                        print(f"Gofile upload failed: HTTP {resp.status} - {text[:300]}")
                        return None

            except Exception as e:
                print(f"Gofile Upload Error: {e}")
                return None

        for attempt in range(3):
            link = await upload()
            if link:
                return link
            print(f"⚠️ محاولة {attempt+1} للفشل في Gofile، إعادة المحاولة...")
            await asyncio.sleep(5)
        return None

    async def upload_to_gofile_legacy(self, file_path: str):
        """
        مسار احتياطي قديم لرفع Gofile إذا احتجناه في الاختبارات اليدوية.
        """
        loop = asyncio.get_event_loop()

        def upload():
            try:
                upload_url = "https://upload.gofile.io/uploadfile"
                headers = {}
                if Config.GOFILE_TOKEN:
                    headers["Authorization"] = f"Bearer {Config.GOFILE_TOKEN}"
                with open(file_path, 'rb') as f:
                    files = {'file': f}
                    resp = requests.post(upload_url, files=files, headers=headers, timeout=600)
                if resp.status_code == 200:
                    resp_data = resp.json().get("data", {})
                    return resp_data.get("downloadPage") or resp_data.get("pageLink")
                else:
                    print(f"Gofile upload failed: HTTP {resp.status_code} - {resp.text[:200]}")
                    return None
            except Exception as e:
                print(f"Gofile Upload Error: {e}")
                return None

        for attempt in range(3):
            link = await loop.run_in_executor(None, upload)
            if link:
                return link
            print(f"⚠️ محاولة {attempt+1} للفشل في Gofile، إعادة المحاولة...")
            await asyncio.sleep(5)
        return None

    def cleanup(self, file_path: str):
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"Cleanup failed for {file_path}: {e}")

    async def download_and_stitch(
        self,
        url: str,
        chapter_title: str,
        target_height: int = 14500,
        target_width: int = 800,
        sensitivity: int = 90,
        progress_callback=None,
        **_ignored_options,
    ) -> str | None:
        """Download a chapter and apply SmartStitch, returning a stitched ZIP."""
        loop = asyncio.get_event_loop()
        # 1. Download raw images as ZIP
        raw_zip = await self.download_chapter(url, chapter_title, progress_callback=progress_callback)
        if not raw_zip:
            return None
        if progress_callback:
            await progress_callback(0, 1, "🪡 دمج الصور (SmartStitch)...")
        # 2. Run SmartStitch in a thread (CPU‑bound)
        stitch_out_dir = os.path.join(self.temp_dir, f"stitched_{uuid.uuid4().hex[:8]}")
        safe_title = chapter_title.replace(" ", "_")
        def run_stitch():
            return smart_stitch_from_zip(
                zip_path=raw_zip,
                output_dir=stitch_out_dir,
                chapter_name=safe_title,
                target_height=target_height,
                target_width=target_width,
                sensitivity=sensitivity,
                output_format="jpg",
                output_quality=95,
            )
        stitched_files = await loop.run_in_executor(None, run_stitch)
        # clean raw zip
        self.cleanup(raw_zip)
        if not stitched_files:
            shutil.rmtree(stitch_out_dir, ignore_errors=True)
            return None
        # 3. Pack stitched files into a new ZIP
        job_id = uuid.uuid4().hex[:8]
        final_zip = os.path.join(self.temp_dir, f"{safe_title}_stitched_{job_id}.zip")
        with zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for f in stitched_files:
                zf.write(f, os.path.basename(f))
        shutil.rmtree(stitch_out_dir, ignore_errors=True)
        if progress_callback:
            await progress_callback(1, 1, f"✅ SmartStitch: {len(stitched_files)} قطعة جاهزة")
        return final_zip

    async def upload_to_gdrive(self, file_path: str, filename: str, progress_callback=None):
        """
        رفع الملف إلى Google Drive مع محاولات إعادة المحاولة.
        """
        loop = asyncio.get_event_loop()
        
        def upload():
            try:
                if not Config.GOOGLE_SERVICE_ACCOUNT_JSON:
                    print("❌ Google Service Account JSON is missing in config.")
                    return None
                if not Config.GOOGLE_DRIVE_FOLDER_ID:
                    print("❌ GOOGLE_DRIVE_FOLDER_ID is missing. Service Accounts need a shared folder/drive target.")
                    return None
                
                info = json.loads(Config.GOOGLE_SERVICE_ACCOUNT_JSON)
                # Fix private key newline issues common in .env files
                if "private_key" in info:
                    info["private_key"] = info["private_key"].replace("\\n", "\n")
                
                creds = service_account.Credentials.from_service_account_info(info)
                service = build('drive', 'v3', credentials=creds)
                
                file_metadata = {
                    'name': filename,
                    'parents': [Config.GOOGLE_DRIVE_FOLDER_ID]
                }
                creds = creds.with_scopes(["https://www.googleapis.com/auth/drive.file"])
                media = MediaFileUpload(file_path, resumable=True, chunksize=1024 * 1024 * 5)
                request = service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id, webViewLink, webContentLink',
                    supportsAllDrives=True
                )
                
                response = None
                while response is None:
                    status, response = request.next_chunk()
                    if status and progress_callback:
                        asyncio.run_coroutine_threadsafe(
                            progress_callback(int(status.progress() * 100), 100, "رفع الملف إلى Drive"), 
                            loop
                        )
                
                file_id = response.get('id')
                service.permissions().create(
                    fileId=file_id,
                    body={'type': 'anyone', 'role': 'viewer'},
                    supportsAllDrives=True
                ).execute()
                if progress_callback:
                    asyncio.run_coroutine_threadsafe(
                        progress_callback(100, 100, "رفع الملف إلى Drive"),
                        loop
                    )
                return response.get('webViewLink') or response.get('webContentLink') or f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
            except HttpError as e:
                msg = str(e)
                if "storageQuotaExceeded" in msg:
                    print("Google Drive quota error: Service Account requires Shared Drive or delegated user storage.")
                else:
                    print(f"Google Drive HTTP Error: {e}")
                return None
            except Exception as e:
                print(f"Google Drive Upload Error: {e}")
                return None

        for attempt in range(3):
            link = await loop.run_in_executor(None, upload)
            if link:
                return link
            print(f"⚠️ محاولة {attempt+1} للفشل في Google Drive، إعادة المحاولة...")
            await asyncio.sleep(5)
        return None
