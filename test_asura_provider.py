import asyncio
from providers.asura_provider import AsuraProvider

def test_get_images():
    provider = AsuraProvider()
    url = "https://vortexscans.org/series/rebirth-of-the-divine-demon/chapter-41"  # رابط حقيقي لفصل
    
    async def run_test():
        images = await provider.get_images(url)
        print("Images:", images)
        assert len(images) > 0, "No images were found!"

    asyncio.run(run_test())

if __name__ == "__main__":
    test_get_images()