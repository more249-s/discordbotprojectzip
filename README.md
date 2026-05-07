# AI Discord Bot (Gemini + Binance) 🤖💰

A powerful Discord bot integrated with Google Gemini AI for intelligent conversations and Binance API for crypto tracking and alerts.

## 🚀 Features
- **AI Chat**: Powered by Google Gemini.
- **Crypto Monitoring**: Real-time balance and price tracking via Binance.
- **Database Support**: Persistent data using SQLite.
- **Manga Downloader**: Built-in tools for tracking and downloading manga.
- **Docker Ready**: Easy deployment using Docker.

## 🛠️ Setup
1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file with your credentials:
   ```env
   DISCORD_TOKEN=your_discord_token
   GEMINI_API_KEY=your_gemini_key
   BINANCE_API_KEY=your_binance_key
   BINANCE_API_SECRET=your_binance_secret
   GOOGLE_DRIVE_FOLDER_ID=your_shared_drive_or_shared_folder_id
   GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account", ...}
   GOFILE_TOKEN=optional_gofile_api_token
   ```
4. Run the bot:
   ```bash
   python main.py
   ```

## 📝 License
MIT
