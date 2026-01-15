import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
NGROK_URL = "https://6e34567b8e3d.ngrok-free.app"  # Update this if ngrok restarts
WEBHOOK_URL = f"{NGROK_URL}/telegram"

def set_webhook():
    if not TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}"
    response = requests.get(url)
    print(f"Setting webhook to: {WEBHOOK_URL}")
    print(response.json())

if __name__ == "__main__":
    set_webhook()
