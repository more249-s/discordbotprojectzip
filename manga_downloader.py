import os
import zipfile
import requests
import cloudscraper
import aiohttp
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

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


class MangaDownloader:
    def __init__(self):
        self.provider_manager = ProviderManager()
        self.scraper          = self.provider_manager.generic.scraper
        self.temp_dir         = "temp_downloads"
        os.makedirs(self.temp_dir, exist_ok=True)

    # ── شريط التقدم ───────────────────────────────────────────────────────
    @staticmethod
    def create_progress_bar(current, total, length=15, style="modern"):
        styles = {
            "modern":  ("▰", "▱", "", ""),
            "dots":    ("●", "○", "", ""),
            "square":  ("■", "□", "", ""),
            "classic": ("#", "-", "[", "]"),
        }
        fill, empty, pre, suf = styles.get(style, styles["modern"])
        if total <= 0:
            return f"{pre}{empty * length}{suf} 0%"
        pct    = max(0.0, min(1.0, float(current) / float(total)))
        filled = int(round(pct * length))
        return f"{pre}{fill * filled}{empty * (length - filled)}{suf} {int(round(pct * 100))}%"

    # ── تحميل فصل ─────────────────────────────────────────────────────────
    async def download_chapter(self, url: str, chapter_title: str, progress_callback=None, **kwargs):
        loop     = asyncio.get_event_loop()
        img_urls = await self.provider_manager.get_images(url)
        if not img_urls:
            return None

        job_id  = str(uuid.uuid4())[:8]
        job_dir = os.path.join(self.temp_dir, job_id)
        os.makedirs(job_dir)
        downloaded_files = []
        completed        = 0

        def download_single(idx, img_url):
            try:
                headers = {
                    "Referer":    url,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                r = self.scraper.get(img_url, stream=True, timeout=30, headers=headers)
                if r.status_code == 200:
                    raw  = r.content
                    ext  = img_url.split('.')[-1].split('?')[0][:4]
                    if not ext or "/" in ext:
                        ext = 'jpg'
                    fp = os.path.join(job_dir, f"{idx:03d}.{ext}")
                    with open(fp, 'wb') as f:
                        f.write(raw)
                    return fp
            except Exception as e:
                print(f"Image {idx} failed: {e}")
            return None

        sem = asyncio.Semaphore(5) # تقليل العدد لتجنب حرق الموارد

        async def dl_limited(idx, u):
            async with sem:
                await asyncio.sleep(0.1) # تأخير بسيط لتقليل الضغط
                return await loop.run_in_executor(None, download_single, idx, u)

        tasks = [dl_limited(i, u) for i, u in enumerate(img_urls)]
        for task in asyncio.as_completed(tasks):
            fp = await task
            if fp:
                downloaded_files.append(fp)
            completed += 1
            if progress_callback and (completed % 2 == 0 or completed == len(img_urls)):
                await progress_callback(completed, len(img_urls), "📥 تحميل الصور")

        if not downloaded_files:
            shutil.rmtree(job_dir)
            return None

        downloaded_files.sort()
        zip_name = f"{chapter_title.replace(' ', '_')}_{job_id}.zip"
        zip_path = os.path.join(self.temp_dir, zip_name)
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for f in downloaded_files:
                zf.write(f, os.path.basename(f))
        shutil.rmtree(job_dir)
        return zip_path

    # ── SmartStitch ────────────────────────────────────────────────────────
    async def download_and_stitch(
        self, url: str, chapter_title: str,
        target_height: int = 14500, target_width: int = 800,
        sensitivity: int = 90, progress_callback=None, **_
    ) -> str | None:
        loop    = asyncio.get_event_loop()
        raw_zip = await self.download_chapter(url, chapter_title, progress_callback=progress_callback)
        if not raw_zip:
            return None
        if progress_callback:
            await progress_callback(0, 1, "🪡 دمج الصور (SmartStitch)...")

        stitch_dir = os.path.join(self.temp_dir, f"stitched_{uuid.uuid4().hex[:8]}")
        safe_title = chapter_title.replace(" ", "_")

        def run_stitch():
            return smart_stitch_from_zip(
                zip_path=raw_zip, output_dir=stitch_dir, chapter_name=safe_title,
                target_height=target_height, target_width=target_width,
                sensitivity=sensitivity, output_format="jpg", output_quality=95,
            )

        stitched = await loop.run_in_executor(None, run_stitch)
        self.cleanup(raw_zip)
        if not stitched:
            shutil.rmtree(stitch_dir, ignore_errors=True)
            return None

        final_zip = os.path.join(self.temp_dir, f"{safe_title}_stitched_{uuid.uuid4().hex[:8]}.zip")
        with zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for f in stitched:
                zf.write(f, os.path.basename(f))
        shutil.rmtree(stitch_dir, ignore_errors=True)
        if progress_callback:
            await progress_callback(1, 1, f"✅ SmartStitch: {len(stitched)} قطعة")
        return final_zip

    # ── رفع Gofile ────────────────────────────────────────────────────────
    async def upload_to_gofile(self, file_path: str, progress_callback=None):
        async def _upload():
            try:
                if progress_callback:
                    await progress_callback(0, 100, "☁️ رفع إلى Gofile")
                boundary = f"----CatBi{uuid.uuid4().hex}"
                filename  = os.path.basename(file_path)
                file_size = os.path.getsize(file_path)
                head  = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                         f"filename=\"{filename}\"\r\nContent-Type: application/zip\r\n\r\n").encode()
                tail  = f"\r\n--{boundary}--\r\n".encode()
                total = len(head) + file_size + len(tail)
                done  = 0
                last  = 0.0

                async def body():
                    nonlocal done, last
                    done += len(head); yield head
                    with open(file_path, "rb") as f:
                        while chunk := f.read(1024 * 1024):
                            done += len(chunk)
                            now   = time.monotonic()
                            if progress_callback and (now - last >= 1.5 or done >= total):
                                last = now
                                await progress_callback(min(99, int(done*100/total)), 100, "☁️ رفع إلى Gofile")
                            yield chunk
                    done += len(tail); yield tail

                hdrs = {"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(total)}
                if Config.GOFILE_TOKEN:
                    hdrs["Authorization"] = f"Bearer {Config.GOFILE_TOKEN}"

                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=900)) as s:
                    async with s.post("https://upload.gofile.io/uploadfile", data=body(), headers=hdrs) as r:
                        txt = await r.text()
                        if r.status == 200:
                            pl = json.loads(txt)
                            if pl.get("status") in ("ok", True):
                                if progress_callback:
                                    await progress_callback(100, 100, "☁️ رفع إلى Gofile")
                                d = pl.get("data", {})
                                return d.get("downloadPage") or d.get("pageLink") or d.get("directLink")
                        print(f"Gofile error: {r.status} {txt[:200]}")
                        return None
            except Exception as e:
                print(f"Gofile error: {e}")
                return None

        for attempt in range(3):
            link = await _upload()
            if link:
                return link
            print(f"Gofile attempt {attempt+1} failed, retrying...")
            await asyncio.sleep(5)
        return None

    # ── رفع Catbox (بديل مجاني بلا حساب) ────────────────────────────────
    async def upload_to_catbox(self, file_path: str, progress_callback=None):
        """رفع إلى catbox.moe — مجاني 200MB max."""
        try:
            if progress_callback:
                await progress_callback(0, 100, "☁️ رفع إلى Catbox")
            filename = os.path.basename(file_path)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as s:
                with open(file_path, "rb") as f:
                    data = aiohttp.FormData()
                    data.add_field("reqtype", "fileupload")
                    data.add_field("fileToUpload", f, filename=filename, content_type="application/zip")
                    async with s.post("https://catbox.moe/user/api.php", data=data) as r:
                        text = await r.text()
                        if r.status == 200 and text.startswith("https://"):
                            if progress_callback:
                                await progress_callback(100, 100, "☁️ رفع إلى Catbox")
                            return text.strip()
                        print(f"Catbox error: {r.status} {text[:200]}")
                        return None
        except Exception as e:
            print(f"Catbox error: {e}")
            return None

    # ── رفع Google Drive ──────────────────────────────────────────────────
    async def upload_to_gdrive(self, file_path: str, filename: str, progress_callback=None):
        loop = asyncio.get_event_loop()

        def _upload():
            try:
                if not Config.GOOGLE_SERVICE_ACCOUNT_JSON:
                    print("❌ GOOGLE_SERVICE_ACCOUNT_JSON مفقود")
                    return None
                if not Config.GOOGLE_DRIVE_FOLDER_ID:
                    print("❌ GOOGLE_DRIVE_FOLDER_ID مفقود")
                    return None

                info = json.loads(Config.GOOGLE_SERVICE_ACCOUNT_JSON)
                if "private_key" in info:
                    info["private_key"] = info["private_key"].replace("\\n", "\n")

                # ✅ إصلاح: scopes من البداية
                creds   = service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
                service = build('drive', 'v3', credentials=creds)

                # فحص هل المجلد Shared Drive
                folder_meta = service.files().get(
                    fileId=Config.GOOGLE_DRIVE_FOLDER_ID,
                    fields="id,name,driveId",
                    supportsAllDrives=True
                ).execute()
                drive_id = folder_meta.get("driveId")

                file_meta = {'name': filename, 'parents': [Config.GOOGLE_DRIVE_FOLDER_ID]}
                kwargs    = dict(body=file_meta, media_body=MediaFileUpload(file_path, resumable=True, chunksize=5*1024*1024),
                                 fields='id,webViewLink,webContentLink', supportsAllDrives=True)
                if drive_id:
                    kwargs['driveId'] = drive_id

                req      = service.files().create(**kwargs)
                response = None
                while response is None:
                    status, response = req.next_chunk()
                    if status and progress_callback:
                        asyncio.run_coroutine_threadsafe(
                            progress_callback(int(status.progress() * 100), 100, "☁️ رفع إلى Google Drive"),
                            loop
                        )

                file_id = response.get('id')
                service.permissions().create(
                    fileId=file_id,
                    body={'type': 'anyone', 'role': 'reader'},
                    supportsAllDrives=True
                ).execute()
                if progress_callback:
                    asyncio.run_coroutine_threadsafe(
                        progress_callback(100, 100, "☁️ رفع إلى Google Drive"), loop
                    )
                return (response.get('webViewLink') or
                        response.get('webContentLink') or
                        f"https://drive.google.com/file/d/{file_id}/view?usp=sharing")

            except HttpError as e:
                msg = str(e)
                if "storageQuotaExceeded" in msg:
                    sa_email = json.loads(Config.GOOGLE_SERVICE_ACCOUNT_JSON).get("client_email", "SA")
                    print(f"❌ Drive: تجاوز الحصة — يرجى إنشاء Shared Drive ومشاركته مع: {sa_email}")
                elif "403" in msg or "forbidden" in msg.lower():
                    print(f"❌ Drive: صلاحيات غير كافية — {e}")
                else:
                    print(f"❌ Drive HTTP Error: {e}")
                return None
            except Exception as e:
                print(f"❌ Drive error: {e}")
                return None

        for attempt in range(2):
            link = await loop.run_in_executor(None, _upload)
            if link:
                return link
            await asyncio.sleep(3)
        return None

    # ── تنظيف ─────────────────────────────────────────────────────────────
    def cleanup(self, file_path: str):
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"Cleanup error: {e}")
