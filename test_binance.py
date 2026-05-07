import asyncio
from binance import AsyncClient
from config import Config

async def test():
    try:
        client = await AsyncClient.create(Config.BINANCE_API_KEY, Config.BINANCE_API_SECRET)
        account = await client.get_account()
        print("Success:", account['balances'][0])
        await client.close_connection()
    except Exception as e:
        print("BINANCE_ERROR:", type(e).__name__, str(e))

asyncio.run(test())
