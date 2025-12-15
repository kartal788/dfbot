import os
import requests
from time import time
from pyrogram import Client, filters
from pyrogram.types import Message
from dotenv import load_dotenv
from Backend.helper.custom_filter import CustomFilters

# .env yükle
load_dotenv()

PIXELDRAIN_API_KEY = os.getenv("PIXELDRAIN")

# Flood ayarları
flood_wait = 30  # saniye
last_command_time = {}

@Client.on_message(filters.command("pixeldrain") & filters.private & CustomFilters.owner)
async def pixeldrain_stats(client: Client, message: Message):
    user_id = message.from_user.id
    now = time()

    # Flood kontrolü
    if user_id in last_command_time and now - last_command_time[user_id] < flood_wait:
        await message.reply_text(f"⚠️ Lütfen {flood_wait} saniye bekleyin.")
        return
    last_command_time[user_id] = now

    if not PIXELDRAIN_API_KEY:
        await message.reply_text("⚠️ PIXELDRAIN API key bulunamadı (.env).")
        return

    try:
        response = requests.get(
            "https://pixeldrain.com/api/account",
            headers={
                "Authorization": f"Bearer {PIXELDRAIN_API_KEY}",
                "User-Agent": "PyrogramBot"
            },
            timeout=15
        )

        if response.status_code != 200:
            await message.reply_text(
                f"⚠️ API Hatası\nKod: `{response.status_code}`\nYanıt: `{response.text}`"
            )
            return

        data = response.json()

        text = (
            "📊 **PixelDrain İstatistikleri**\n\n"
            f"👤 Kullanıcı: `{data.get('username', 'Bilinmiyor')}`\n"
            f"📦 Dosya Sayısı: `{data.get('file_count', 'N/A')}`\n"
            f"💾 Depolama: `{data.get('storage_used', 'N/A')}`\n"
            f"🌐 Trafik: `{data.get('bandwidth_used', 'N/A')}`\n"
            f"⭐ Plan: `{data.get('plan', 'N/A')}`"
        )

        await message.reply_text(text)

    except Exception as e:
        await message.reply_text(f"⚠️ Beklenmeyen hata:\n`{e}`")
