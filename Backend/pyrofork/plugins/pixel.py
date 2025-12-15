import os
import requests
import base64
import asyncio
from time import time
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from dotenv import load_dotenv
from Backend.helper.custom_filter import CustomFilters

load_dotenv()

PIXELDRAIN_API_KEY = os.getenv("PIXELDRAIN")
API_BASE = "https://pixeldrain.com/api"
CMD_FLOOD_WAIT = 60
last_command_time = {}

def get_headers():
    auth = base64.b64encode(f":{PIXELDRAIN_API_KEY}".encode()).decode()
    return {
        "Authorization": f"Basic {auth}",
        "User-Agent": "PyrogramBot"
    }

def human_size(size):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

def fetch_all_files_safe(max_pages=100):
    page = 1
    all_files = []

    while page <= max_pages:
        r = requests.get(
            f"{API_BASE}/user/files?page={page}",
            headers=get_headers(),
            timeout=15
        )

        if r.status_code != 200:
            break

        data = r.json()
        files = data.get("files", [])
        if not files:
            break

        all_files.extend(files)
        page += 1

    return all_files

async def safe_reply(message: Message, text: str):
    try:
        return await message.reply_text(text)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await message.reply_text(text)

async def safe_edit(msg: Message, text: str):
    try:
        await msg.edit_text(text)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await msg.edit_text(text)

@Client.on_message(filters.command("pixeldrain") & filters.private & CustomFilters.owner)
async def pixeldrain_handler(client: Client, message: Message):
    user_id = message.from_user.id
    now = time()

    if user_id in last_command_time and now - last_command_time[user_id] < CMD_FLOOD_WAIT:
        await safe_reply(message, "Lütfen biraz bekleyin.")
        return
    last_command_time[user_id] = now

    if not PIXELDRAIN_API_KEY:
        await safe_reply(message, "PIXELDRAIN API key yok.")
        return

    args = message.command[1:]
    status = await safe_reply(message, "Veriler alınıyor...")

    try:
        files = await asyncio.to_thread(fetch_all_files_safe)

        # /pixeldrain sil
        if args and args[0].lower() == "sil":
            deleted = 0

            for f in files:
                file_id = f.get("id")
                if not file_id:
                    continue

                r = requests.delete(
                    f"{API_BASE}/file/{file_id}",
                    headers=get_headers(),
                    timeout=10
                )

                if r.status_code == 200:
                    deleted += 1

                await asyncio.sleep(0.3)

            await safe_edit(
                status,
                f"🗑️ Silme tamamlandı.\nSilinen dosya sayısı: {deleted}"
            )
            return

        # /pixeldrain listeleme
        total_bytes = 0
        text = "📦 **PixelDrain Dosyalar**\n\n"

        for i, f in enumerate(files, start=1):
            name = f.get("name", "Bilinmiyor")
            size = f.get("size", 0)
            total_bytes += size

            text += f"{i}. `{name}` — {human_size(size)}\n"

            if len(text) > 3500:
                text += "\n⚠️ Liste kısaltıldı."
                break

        text += (
            "\n\n📊 **Toplam Kullanım**\n"
            f"Dosya Sayısı: {len(files)}\n"
            f"Toplam Boyut: {human_size(total_bytes)}\n\n"
            "🗑️ Tüm dosyaları silmek için:\n"
            "`/pixeldrain sil`"
        )

        await safe_edit(status, text)

    except Exception as e:
        await safe_edit(status, "❌ Hata oluştu.")
        print("PixelDrain hata:", e)
