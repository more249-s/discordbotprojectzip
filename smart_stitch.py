"""
SmartStitch Engine - Inspired by MechTechnology/SmartStitch
ستيتش صور الويبتون/المانهوا عمودياً ثم يقطعها بذكاء بعيداً عن الفقاعات والنصوص.

Usage:
    pages = smart_stitch(image_paths, target_height=14500, target_width=800,
                         sensitivity=90, scan_step=5, ignorable_border=5)
    # Returns list of PIL Image objects
"""

import os
import sys
import numpy as np
from PIL import Image
from typing import List, Optional, Tuple


# ─────────────────────────── helpers ────────────────────────────────────────

def _log(message: str):
    try:
        print(message)
    except UnicodeEncodeError:
        safe = str(message).encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8")
        print(safe)

def _load_images(paths: List[str]) -> List[Image.Image]:
    """تحميل الصور وتحويلها إلى RGB."""
    imgs = []
    for p in paths:
        try:
            img = Image.open(p).convert("RGB")
            imgs.append(img)
        except Exception as e:
            _log(f"[SmartStitch] warning - failed to load {p}: {e}")
    return imgs


def _resize_to_width(imgs: List[Image.Image], width: int) -> List[Image.Image]:
    """تغيير حجم كل الصور لنفس العرض مع الحفاظ على النسبة."""
    resized = []
    for img in imgs:
        if img.width != width:
            ratio = width / img.width
            new_h = max(1, int(img.height * ratio))
            img = img.resize((width, new_h), Image.LANCZOS)
        resized.append(img)
    return resized


def _stitch_vertically(imgs: List[Image.Image]) -> Image.Image:
    """دمج قائمة الصور عمودياً في صورة واحدة."""
    total_h = sum(i.height for i in imgs)
    width = imgs[0].width
    canvas = Image.new("RGB", (width, total_h), (255, 255, 255))
    y = 0
    for img in imgs:
        canvas.paste(img, (0, y))
        y += img.height
    return canvas


def _is_safe_row(arr: np.ndarray, row: int, sensitivity: int,
                 ignorable_border: int) -> bool:
    """
    تحقق إذا كان الصف آمناً للقطع.
    - sensitivity 0  → يقطع بغض النظر
    - sensitivity 100 → يقطع فقط إذا كل البكسلات متطابقة
    """
    if sensitivity == 0:
        return True

    height, width, _ = arr.shape
    if row <= 0 or row >= height:
        return False

    left = ignorable_border
    right = width - ignorable_border
    if left >= right:
        left, right = 0, width

    row_data = arr[row, left:right].astype(np.int32)
    if len(row_data) < 2:
        return True

    # حساب الفرق بين البكسلات المتجاورة
    diffs = np.abs(np.diff(row_data, axis=0))
    max_diff = diffs.max() if len(diffs) > 0 else 0

    # threshold بناءً على الـ sensitivity (100 → 0 tolerance)
    threshold = (100 - sensitivity) * 2.55  # 0..255
    return max_diff <= threshold


def _find_safe_slice_point(arr: np.ndarray, target_y: int,
                           sensitivity: int, scan_step: int,
                           ignorable_border: int,
                           search_range: int = 500) -> int:
    """
    يبحث عن أقرب صف آمن للقطع حول target_y.
    يبحث للأعلى أولاً ثم للأسفل ضمن search_range بكسل.
    """
    height = arr.shape[0]

    # ابحث أولاً في الاتجاه نحو الأعلى (أكثر أماناً)
    for delta in range(0, search_range, scan_step):
        # أعلى
        y_up = target_y - delta
        if y_up > 0 and _is_safe_row(arr, y_up, sensitivity, ignorable_border):
            return y_up
        # أسفل
        y_down = target_y + delta
        if y_down < height and _is_safe_row(arr, y_down, sensitivity, ignorable_border):
            return y_down

    # إذا ما لقينا أي صف آمن - نقطع في target_y مباشرة
    return min(target_y, height)


# ─────────────────────────── main function ──────────────────────────────────

def smart_stitch(
    image_paths: List[str],
    target_height: int = 14500,
    target_width: int = 800,
    sensitivity: int = 90,
    scan_step: int = 5,
    ignorable_border: int = 5,
    output_format: str = "jpg",
    output_quality: int = 95,
) -> List[Image.Image]:
    """
    يدمج قائمة صور المانجا عمودياً ثم يقطعها بذكاء.

    Parameters
    ----------
    image_paths    : مسارات ملفات الصور (مرتّبة)
    target_height  : الارتفاع التقريبي لكل قطعة ناتجة (px)
    target_width   : العرض الموحّد للصور (px)
    sensitivity    : حساسية كشف الكائنات 0-100 (90 = لا يقطع إذا اختلف 10%)
    scan_step      : خطوة البحث عن صف آمن (px)
    ignorable_border: هامش البكسلات المتجاهل من الجانبين
    output_format  : صيغة الصورة الناتجة
    output_quality : جودة ملفات الـ jpg

    Returns
    -------
    list of PIL Image objects (القطع الناتجة)
    """
    if not image_paths:
        return []

    _log(f"[SmartStitch] loading {len(image_paths)} images...")
    imgs = _load_images(image_paths)
    if not imgs:
        return []

    _log(f"[SmartStitch] resizing to {target_width}px width...")
    imgs = _resize_to_width(imgs, target_width)

    _log("[SmartStitch] stitching images vertically...")
    stitched = _stitch_vertically(imgs)
    total_height = stitched.height
    _log(f"[SmartStitch] total height: {total_height}px")

    # تحويل لـ numpy للمعالجة السريعة
    arr = np.array(stitched)

    # ─── القطع الذكي ───
    slices: List[Image.Image] = []
    current_y = 0
    part = 1

    while current_y < total_height:
        raw_next = current_y + target_height

        if raw_next >= total_height:
            # القطعة الأخيرة
            slice_img = stitched.crop((0, current_y, target_width, total_height))
            slices.append(slice_img)
            _log(f"[SmartStitch] part {part}: {current_y}->{total_height} (last)")
            break

        # ابحث عن صف آمن
        safe_y = _find_safe_slice_point(
            arr, raw_next, sensitivity, scan_step, ignorable_border
        )
        safe_y = max(current_y + 1, min(safe_y, total_height))

        slice_img = stitched.crop((0, current_y, target_width, safe_y))
        slices.append(slice_img)
        _log(f"[SmartStitch] part {part}: {current_y}->{safe_y} ({safe_y - current_y}px)")

        current_y = safe_y
        part += 1

    _log(f"[SmartStitch] done: {len(slices)} output parts")
    return slices


def smart_stitch_to_files(
    image_paths: List[str],
    output_dir: str,
    chapter_name: str = "chapter",
    target_height: int = 14500,
    target_width: int = 800,
    sensitivity: int = 90,
    scan_step: int = 5,
    ignorable_border: int = 5,
    output_format: str = "jpg",
    output_quality: int = 95,
) -> List[str]:
    """
    نفس smart_stitch لكن يحفظ النتائج كملفات ويُرجع قائمة المسارات.
    """
    slices = smart_stitch(
        image_paths=image_paths,
        target_height=target_height,
        target_width=target_width,
        sensitivity=sensitivity,
        scan_step=scan_step,
        ignorable_border=ignorable_border,
        output_format=output_format,
        output_quality=output_quality,
    )

    os.makedirs(output_dir, exist_ok=True)
    saved = []
    for i, img in enumerate(slices):
        ext = output_format.lstrip(".")
        filename = f"{chapter_name}_p{i+1:02d}.{ext}"
        filepath = os.path.join(output_dir, filename)
        if ext in ("jpg", "jpeg"):
            img.save(filepath, "JPEG", quality=output_quality)
        elif ext == "webp":
            img.save(filepath, "WEBP", quality=output_quality)
        else:
            img.save(filepath, ext.upper())
        saved.append(filepath)

    return saved


def smart_stitch_from_zip(
    zip_path: str,
    output_dir: str,
    chapter_name: str = "chapter",
    target_height: int = 14500,
    target_width: int = 800,
    sensitivity: int = 90,
    scan_step: int = 5,
    ignorable_border: int = 5,
    output_format: str = "jpg",
    output_quality: int = 95,
) -> List[str]:
    """
    استخراج ملف ZIP وتطبيق SmartStitch مباشرةً.
    مناسب للاستخدام بعد تحميل الفصل.
    """
    import zipfile, tempfile, shutil

    tmp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)

        # ترتيب الملفات أبجدياً (000.jpg, 001.jpg ...)
        supported = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
        files = sorted([
            os.path.join(tmp_dir, f)
            for f in os.listdir(tmp_dir)
            if os.path.splitext(f)[1].lower() in supported
        ])

        return smart_stitch_to_files(
            image_paths=files,
            output_dir=output_dir,
            chapter_name=chapter_name,
            target_height=target_height,
            target_width=target_width,
            sensitivity=sensitivity,
            scan_step=scan_step,
            ignorable_border=ignorable_border,
            output_format=output_format,
            output_quality=output_quality,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
