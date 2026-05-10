"""
drive_stitch.py — تحميل صور من Google Drive وتطبيق SmartStitch عليها
يدعم:
  - رابط مجلد Google Drive: https://drive.google.com/drive/folders/...
  - رابط ملف عادي (ZIP): https://drive.google.com/file/d/.../view
  - رابط مشاركة مباشر
"""

import os
import io
import re
import json
import uuid
import shutil
import asyncio
import zipfile
import tempfile
from typing import Optional, Callable

import aiohttp
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

from config import Config
from smart_stitch import smart_stitch_to_files

DRIVE_SCOPES     = ["https://www.googleapis.com/auth/drive.readonly"]
SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


def _get_drive_service():
    if not Config.GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON غير موجود")
    info = json.loads(Config.GOOGLE_SERVICE_ACCOUNT_JSON)
    if "private_key" in info:
        info["private_key"] = info["private_key"].replace("\\n", "\n")
    creds   = service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
    service = build("drive", "v3", credentials=creds)
    return service


def _extract_id(url: str) -> Optional[str]:
    """استخراج الـ ID من روابط Drive المختلفة."""
    patterns = [
        r"drive\.google\.com/drive/folders/([a-zA-Z0-9_-]+)",
        r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)",
        r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)",
        r"drive\.google\.com/.*[?&]id=([a-zA-Z0-9_-]+)",
        r"docs\.google\.com/.*?/d/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]{25,})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    # Raw ID
    parts = url.strip("/").split("/")
    for part in reversed(parts):
        if len(part) >= 25 and re.match(r'^[a-zA-Z0-9_-]+$', part):
            return part
    return None


def _download_file(service, file_id: str, dest_path: str, progress_cb=None):
    """تحميل ملف من Drive."""
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    with open(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=4 * 1024 * 1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if progress_cb and status:
                progress_cb(int(status.progress() * 100))


def _list_folder(service, folder_id: str) -> list:
    """قائمة الملفات في مجلد."""
    items = []
    page_token = None
    while True:
        kwargs = dict(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id, name, mimeType)",
            orderBy="name",
            pageSize=200,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        if page_token:
            kwargs["pageToken"] = page_token
        result     = service.files().list(**kwargs).execute()
        items     += result.get("files", [])
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return items


async def stitch_from_drive(
    drive_url: str,
    title: str = "chapter",
    target_height: int = 14500,
    target_width: int  = 800,
    sensitivity: int   = 90,
    progress_callback: Optional[Callable] = None,
    output_dir: str = "temp_downloads",
) -> Optional[str]:
    """
    الدالة الرئيسية: تحميل من Drive وتطبيق SmartStitch.
    Returns: مسار ZIP الناتج أو None عند الفشل
    """
    loop    = asyncio.get_event_loop()
    job_id  = uuid.uuid4().hex[:8]
    work_dir = os.path.join(output_dir, f"drive_{job_id}")
    os.makedirs(work_dir, exist_ok=True)

    async def _pcb(pct: int, msg: str):
        if progress_callback:
            await progress_callback(pct, 100, msg)

    try:
        drive_id = _extract_id(drive_url)
        if not drive_id:
            raise ValueError(f"تعذّر استخراج Drive ID من: {drive_url}")

        await _pcb(2, "🔗 الاتصال بـ Google Drive...")

        def _fetch_meta():
            svc = _get_drive_service()
            meta = svc.files().get(
                fileId=drive_id,
                fields="id, name, mimeType",
                supportsAllDrives=True,
            ).execute()
            return svc, meta

        svc, meta = await loop.run_in_executor(None, _fetch_meta)
        mime = meta.get("mimeType", "")
        name = meta.get("name", title)

        image_paths: list[str] = []

        # ── مجلد → تحميل كل الصور بداخله ────────────────────────────────
        if mime == "application/vnd.google-apps.folder":
            await _pcb(5, f"📂 جلب قائمة الصور من مجلد: {name}")

            def _get_images():
                return [
                    f for f in _list_folder(svc, drive_id)
                    if any(f["name"].lower().endswith(ext) for ext in SUPPORTED_IMAGES)
                    or f["mimeType"].startswith("image/")
                ]

            files = await loop.run_in_executor(None, _get_images)
            if not files:
                raise ValueError("لم تُعثر على صور في المجلد")

            total = len(files)
            await _pcb(8, f"📥 تحميل {total} صورة من Drive...")

            def _dl_all():
                paths = []
                for i, f in enumerate(files):
                    ext = os.path.splitext(f["name"])[1] or ".jpg"
                    dest = os.path.join(work_dir, f"{i:04d}{ext}")
                    try:
                        _download_file(svc, f["id"], dest)
                        paths.append(dest)
                    except Exception as e:
                        print(f"[DriveStitch] skip {f['name']}: {e}")
                return sorted(paths)

            image_paths = await loop.run_in_executor(None, _dl_all)

        # ── ملف ZIP → فك الضغط ───────────────────────────────────────────
        elif mime == "application/zip" or name.lower().endswith(".zip"):
            await _pcb(5, f"📥 تحميل ملف ZIP: {name}")
            zip_path = os.path.join(work_dir, "source.zip")

            def _dl_zip():
                _download_file(svc, drive_id, zip_path)

            await loop.run_in_executor(None, _dl_zip)
            await _pcb(30, "📦 فك ضغط الملف...")

            def _extract():
                extract_dir = os.path.join(work_dir, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(extract_dir)
                imgs = []
                for root, _, fnames in os.walk(extract_dir):
                    for fn in sorted(fnames):
                        if os.path.splitext(fn)[1].lower() in SUPPORTED_IMAGES:
                            imgs.append(os.path.join(root, fn))
                return sorted(imgs)

            image_paths = await loop.run_in_executor(None, _extract)

        # ── صورة واحدة مباشرة ─────────────────────────────────────────────
        elif mime.startswith("image/"):
            await _pcb(5, f"📥 تحميل الصورة: {name}")
            ext  = os.path.splitext(name)[1] or ".jpg"
            dest = os.path.join(work_dir, f"0001{ext}")

            def _dl_img():
                _download_file(svc, drive_id, dest)

            await loop.run_in_executor(None, _dl_img)
            image_paths = [dest]

        else:
            raise ValueError(f"نوع الملف غير مدعوم: {mime}")

        if not image_paths:
            raise ValueError("لم تُعثر على صور للمعالجة")

        await _pcb(40, f"🧵 تطبيق SmartStitch على {len(image_paths)} صورة...")

        stitch_out = os.path.join(work_dir, "stitched")

        safe_title = title.replace(" ", "_")

        def _run_stitch():
            return smart_stitch_to_files(
                image_paths=image_paths,
                output_dir=stitch_out,
                chapter_name=safe_title,
                target_height=target_height,
                target_width=target_width,
                sensitivity=sensitivity,
                output_format="jpg",
                output_quality=95,
            )

        stitched = await loop.run_in_executor(None, _run_stitch)
        if not stitched:
            raise ValueError("SmartStitch فشل في معالجة الصور")

        await _pcb(80, f"📦 ضغط {len(stitched)} قطعة في ZIP...")

        final_zip = os.path.join(output_dir, f"{safe_title}_stitched_{job_id}.zip")

        def _make_zip():
            with zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for f in stitched:
                    zf.write(f, os.path.basename(f))

        await loop.run_in_executor(None, _make_zip)
        await _pcb(100, f"✅ SmartStitch: {len(stitched)} قطعة جاهزة")

        return final_zip

    except Exception as e:
        print(f"[DriveStitch] Error: {e}")
        if progress_callback:
            await progress_callback(0, 100, f"❌ خطأ: {e}")
        return None
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
