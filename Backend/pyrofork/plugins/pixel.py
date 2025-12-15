import os
import requests
import base64
from time import time
from pyrogram import Client, filters
from pyrogram.types import Message
from dotenv import load_dotenv
from Backend.helper.custom_filter import CustomFilters

load_dotenv()

PIXELDRAIN_API_KEY = os.getenv("PIXELDRAIN")

FLOOD_WAIT = 30
last_command_time = {}

@Client.on_message(filters.command("pixeldrain") & filters.private & CustomFilters.owner)
async def pixeldrain_stats(client: Client, message: Message):
    user_id = message.from_user.id
    now = time()

    if user_id in last_command_time and now - last_command_time[user_id] < FLOOD_WAIT:
        await message.reply_text(f"Lütfen {FLOOD_WAIT} saniye bekleyin.")
        return
    last_command_time[user_id] = now

    if not PIXELDRAIN_API_KEY:
        await message.reply_text("PIXELDRAIN API key bulunamadı.")
        return

    try:
        auth = base64.b64encode(f":{PIXELDRAIN_API_KEY}".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth}",
            "User-Agent": "PyrogramBot"
        }

        response = requests.get(
            "https://pixeldrain.com/api/user/files",
            headers=headers,
            timeout=15
        )

        if response.status_code != 200:
            await message.reply_text(f"API Hatası\nHTTP Kod: {response.status_code}")
            return

        data = response.json()

        total_files = data.get("total", 0)
        page = data.get("page", 1)
        files_on_page = len(data.get("files", []))

        text = (
            "PixelDrain Bilgileri\n\n"
            f"Toplam Dosya Sayısı: {total_files}\n"
            f"Bu Sayfadaki Dosya: {files_on_page}\n"
            f"Sayfa: {page}"
        )

        await message.reply_text(text)

    except Exception as e:
        await message.reply_text("Bir hata oluştu.")
        print("PixelDrain hata:", e)
