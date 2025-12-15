import os
import base64
import requests
import asyncio
from time import time

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait

from dotenv import load_dotenv
from Backend.helper.custom_filter import CustomFilters

# ===================== CONFIG =====================

load_dotenv()

PIXELDRAIN_API_KEY = os.getenv("PIXELDRAIN")
API_BASE = "https://pixeldrain.com/api"
UPDATE_INTERVAL = 15

# ===================== SAFE TELEGRAM =====================

async def safe_reply(message: Message, text: str):
    try:
        return await message.reply_text(text)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await message.reply_text(text)

async def safe_edit(message: Message, text: str):
    try:
        return await message.edit_text(text)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await message.edit_text(text)

# ===================== UTIL =====================

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

def format_duration(seconds: int):
    if seconds < 0:
        return "--:--"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:02}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"

def progress_bar(done, total, length=20):
    if total == 0:
        return "[░░░░░░░░░░░░░░░░░░░░] 0%"
    percent = int((done / total) * 100)
    filled = int(length * done / total)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent}%"

async def auto_update_status(msg, get_text, stop_event):
    while not stop_event.is_set():
        try:
            await safe_edit(msg, get_text())
        except Exception:
            pass
        await asyncio.sleep(UPDATE_INTERVAL)

def format_file_list(files):
    """
    files = [{"name": str, "size": int}]
    alfabetik sıralı + numaralı + boyutlu
    """
    files = sorted(files, key=lambda x: x["name"].lower())
    return "\n".join(
        f"{i+1}. {f['name']} ({human_size(f['size'])})"
        for i, f in enumerate(files)
    )

# ===================== PIXELDRAIN API =====================

def fetch_all_files_safe(max_pages=100):
    page = 1
    files = {}

    while page <= max_pages:
        r = requests.get(
            f"{API_BASE}/user/files?page={page}",
            headers=get_headers(),
            timeout=15
        )
        if r.status_code != 200:
            break

        data = r.json().get("files", [])
        if not data:
            break

        for f in data:
            if f.get("id"):
                files[f["id"]] = f

        page += 1

    return list(files.values())

# ===================== /PIXELDRAINSIL =====================

@Client.on_message(filters.command("pixeldrainsil") & filters.private & CustomFilters.owner)
async def pixeldrain_delete_all(client: Client, message: Message):
    status = await safe_reply(message, "🗑️ PixelDrain silme başlatılıyor...")

    stop_event = asyncio.Event()
    start_time = time()

    deleted = 0
    total = 0
    deleted_files = []

    def progress_text():
        elapsed = int(time() - start_time)
        eta = int((total - deleted) / (deleted / elapsed)) if deleted > 0 else -1
        return (
            "🔄 **PixelDrain Silme Durumu**\n\n"
            f"⏱️ Geçen Süre  : {format_duration(elapsed)}\n"
            f"📊 İlerleme    : {progress_bar(deleted, total)}\n"
            f"📁 İşlenen     : {deleted} / {total}\n"
            f"⏳ Kalan Süre  : {format_duration(eta)}"
        )

    updater = asyncio.create_task(
        auto_update_status(status, progress_text, stop_event)
    )

    try:
        files = await asyncio.to_thread(fetch_all_files_safe)
        total = len(files)

        if total == 0:
            stop_event.set()
            updater.cancel()
            await safe_edit(status, "ℹ️ Silinecek dosya yok.")
            return

        for f in files:
            await asyncio.to_thread(
                requests.delete,
                f"{API_BASE}/file/{f['id']}",
                headers=get_headers(),
                timeout=10
            )
            deleted += 1
            deleted_files.append({
                "name": f.get("name", "isimsiz"),
                "size": f.get("size", 0)
            })
            await asyncio.sleep(0.3)

        stop_event.set()
        updater.cancel()
        elapsed = int(time() - start_time)

        if len(deleted_files) <= 10:
            await safe_edit(
                status,
                "🧹 **PixelDrain Silme Özeti**\n\n"
                f"📁 Silinen Dosya : {deleted}\n"
                f"⏱️ Geçen Süre   : {format_duration(elapsed)}\n\n"
                "📄 **Silinen Dosyalar:**\n" +
                format_file_list(deleted_files)
            )
        else:
            path = "silinen_dosyalar.txt"
            with open(path, "w", encoding="utf-8") as f:
                f.write(format_file_list(deleted_files))

            await client.send_document(
                message.chat.id,
                path,
                caption=(
                    "🧹 **PixelDrain Silme Özeti**\n\n"
                    f"📁 Silinen Dosya : {deleted}\n"
                    f"⏱️ Geçen Süre   : {format_duration(elapsed)}"
                )
            )
            await status.delete()
            os.remove(path)

    except Exception as e:
        stop_event.set()
        updater.cancel()
        await safe_edit(status, "❌ Silme sırasında hata oluştu.")
        print("PixelDrain delete error:", e)

# ===================== /PIXELDRAIN =====================

@Client.on_message(filters.command("pixeldrain") & filters.private & CustomFilters.owner)
async def pixeldrain_list(client: Client, message: Message):
    status = await safe_reply(message, "📂 PixelDrain dosyaları alınıyor...")

    stop_event = asyncio.Event()
    start_time = time()

    updater = asyncio.create_task(
        auto_update_status(
            status,
            lambda: "🔄 **PixelDrain Listeleme Devam Ediyor...**",
            stop_event
        )
    )

    try:
        files = await asyncio.to_thread(fetch_all_files_safe)
        elapsed = int(time() - start_time)

        file_data = [
            {"name": f.get("name", "isimsiz"), "size": f.get("size", 0)}
            for f in files
        ]
        total_bytes = sum(f["size"] for f in file_data)

        stop_event.set()
        updater.cancel()

        if len(file_data) <= 10:
            await safe_edit(
                status,
                "📊 **PixelDrain Özeti**\n\n"
                f"📁 Dosya Sayısı : {len(file_data)}\n"
                f"💾 Toplam Boyut : {human_size(total_bytes)}\n"
                f"⏱️ Geçen Süre  : {format_duration(elapsed)}\n\n"
                "📄 **Dosyalar:**\n" +
                format_file_list(file_data)
            )
        else:
            path = "dosyalar.txt"
            with open(path, "w", encoding="utf-8") as f:
                f.write(format_file_list(file_data))

            await client.send_document(
                message.chat.id,
                path,
                caption=(
                    "📊 **PixelDrain Özeti**\n\n"
                    f"📁 Dosya Sayısı : {len(file_data)}\n"
                    f"💾 Toplam Boyut : {human_size(total_bytes)}\n"
                    f"⏱️ Geçen Süre  : {format_duration(elapsed)}"
                )
            )
            await status.delete()
            os.remove(path)

    except Exception as e:
        stop_event.set()
        updater.cancel()
        await safe_edit(status, "❌ Listeleme sırasında hata oluştu.")
        print("PixelDrain list error:", e)
