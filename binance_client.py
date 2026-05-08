from binance import AsyncClient
from config import Config
import database
import asyncio

class BinanceMonitor:
    def __init__(self, bot):
        self.bot = bot
        self.api_key = Config.BINANCE_API_KEY
        self.api_secret = Config.BINANCE_API_SECRET
        self.client = None

    async def start(self):
        try:
            self.client = await AsyncClient.create(self.api_key, self.api_secret)
        except Exception as e:
            print(f"Warning: Binance connection failed (may be geo-restricted): {e}")
            self.client = None

    async def check_deposits(self):
        if not self.client:
            return []
        
        try:
            # Get deposit history
            deposits = await self.client.get_deposit_history()
            new_deposits = []
            
            for d in deposits:
                tx_id = d['txId']
                if await database.is_transaction_new(tx_id):
                    # Save to DB
                    await database.save_transaction(
                        tx_id, d['amount'], d['coin'], d['insertTime'], "deposit"
                    )
                    new_deposits.append(d)
            
            return new_deposits
        except Exception as e:
            print(f"Error checking Binance deposits: {e}")
            return []

    async def check_withdrawals(self):
        if not self.client:
            return []
        try:
            withdrawals = await self.client.get_withdraw_history()
            new_withdraws = []
            for w in withdrawals:
                tx_id = w.get('id') or w.get('txId')
                if tx_id and await database.is_transaction_new(tx_id):
                    await database.save_transaction(
                        tx_id, w['amount'], w['coin'], w['applyTime'], "withdrawal"
                    )
                    new_withdraws.append(w)
            return new_withdraws
        except Exception as e:
            print(f"Error checking Binance withdrawals: {e}")
            return []

    async def get_symbol_price(self, symbol):
        if not self.client:
            return None
        try:
            res = await self.client.get_symbol_ticker(symbol=symbol.upper())
            return res['price']
        except:
            return None

    async def get_account_balances(self):
        try:
            combined_balances = []
            
            # 1. Get Spot Wallet Balances
            try:
                spot_info = await self.client.get_account()
                for b in spot_info['balances']:
                    if float(b['free']) > 0 or float(b['locked']) > 0:
                        b['type'] = 'Spot'
                        combined_balances.append(b)
            except Exception as e:
                print(f"Error fetching Spot balances: {e}")

            # 2. Get Funding Wallet Balances
            try:
                funding_info = await self.client.funding_wallet()
                if funding_info:
                    for b in funding_info:
                        if float(b['free']) > 0 or float(b['locked']) > 0:
                            b['type'] = 'Funding'
                            combined_balances.append(b)
            except Exception as e:
                print(f"Error fetching Funding balances: {e}")

            return combined_balances
        except Exception as e:
            print(f"DEBUG: Detailed Binance Error: {str(e)}")
            return None
            
    async def close(self):
        if self.client:
            await self.client.close_connection()
