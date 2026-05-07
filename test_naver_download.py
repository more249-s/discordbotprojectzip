import asyncio
import os
import sys
from manga_downloader import MangaDownloader

# Fix Unicode error for Windows terminal
if sys.platform == "win32":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def test_download():
    downloader = MangaDownloader()
    url = "https://comic.naver.com/webtoon/detail?titleId=841762&no=38&week=sat"
    chapter_title = "Naver_Test_Chapter_38"
    
    print(f"Starting download for: {url}")
    
    async def progress(current, total, task):
        print(f"{task}: {current}/{total} {MangaDownloader.create_progress_bar(current, total)}")

    file_path = await downloader.download_chapter(url, chapter_title, progress_callback=progress)
    
    if file_path:
        print(f"Download successful! File saved at: {file_path}")
    else:
        print("Download failed.")

if __name__ == "__main__":
    asyncio.run(test_download())
