import asyncio
from binance import AsyncClient
from config import Config

async def test():
    client = await AsyncClient.create(Config.BINANCE_API_KEY, Config.BINANCE_API_SECRET)
    info = await client.get_account()
    balances = [b for b in info['balances'] if float(b['free']) > 0 or float(b['locked']) > 0]
    print(balances)
    
    # Also check funding wallet just in case
    try:
        funding = await client.funding_wallet()
        funding_balances = [b for b in funding if float(b['free']) > 0 or float(b['locked']) > 0]
        print("Funding:", funding_balances)
    except Exception as e:
        print("Funding error:", e)
        
    await client.close_connection()

asyncio.run(test())
