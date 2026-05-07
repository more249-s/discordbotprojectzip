import asyncio
import os
import sys
from manga_downloader import MangaDownloader

# Fix Unicode error for Windows terminal
if sys.platform == "win32":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def verify():
    downloader = MangaDownloader()
    url = "https://comic.naver.com/webtoon/detail?titleId=841762&no=38&week=sat"
    chapter_title = "Naver_Final_Test"
    
    print(f"🚀 البدء في التحميل والدمج الذكي (SmartStitch)...")
    print(f"🔗 الرابط: {url}")
    
    async def progress(current, total, task):
        print(f"[{task}] {current}/{total} {MangaDownloader.create_progress_bar(current, total)}")

    try:
        final_file = await downloader.download_and_stitch(
            url=url, 
            chapter_title=chapter_title, 
            target_height=14500, 
            target_width=800, 
            progress_callback=progress
        )
        
        if final_file and os.path.exists(final_file):
            print(f"\n✅ نجحت العملية!")
            print(f"📂 الملف النهائي: {final_file}")
            print(f"⚖️ الحجم: {os.path.getsize(final_file) / (1024*1024):.2f} MB")
            
            # التحقق من محتوى الملف للتأكد من الدمج
            import zipfile
            with zipfile.ZipFile(final_file, 'r') as z:
                files = z.namelist()
                print(f"🖼️ عدد القطع المدمجة الناتجة: {len(files)}")
                for f in files:
                    print(f"  - {f}")
        else:
            print("\n❌ فشلت العملية.")
    except Exception as e:
        print(f"\n❌ خطأ: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify())
