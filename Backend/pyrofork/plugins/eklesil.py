import os
import re
from datetime import datetime

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient

from Backend.helper.custom_filter import CustomFilters
from Backend.helper.metadata import metadata
from Backend.logger import LOGGER

# ----------------- ENV -----------------
DATABASE_RAW = os.getenv("DATABASE", "")
db_urls = [u.strip() for u in DATABASE_RAW.split(",") if u.strip().startswith("mongodb")]
MONGO_URL = db_urls[1]
DB_NAME = "dbFyvio"

# ----------------- MongoDB -----------------
mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo[DB_NAME]
movie_col = db["movie"]
series_col = db["tv"]

# ----------------- Helpers -----------------
def pixeldrain_to_api(url: str) -> str:
    m = re.match(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)", url)
    if not m:
        return url
    return f"https://pixeldrain.com/api/file/{m.group(1)}"

async def filename_from_url(url):
    # URL erişilemese bile filename çıkar
    try:
        async with aiohttp.ClientSession() as s:
            async with s.head(url, allow_redirects=True, timeout=10) as r:
                cd = r.headers.get("Content-Disposition")
                if cd:
                    m = re.search(r'filename="(.+?)"', cd)
                    if m:
                        return m.group(1)
        return url.split("/")[-1]
    except Exception:
        return url.split("/")[-1]

async def filesize(url):
    # Her durumda "YOK"
    return "YOK"

# ----------------- /EKLE -----------------
@Client.on_message(filters.command("ekle") & filters.private & CustomFilters.owner)
async def ekle(client: Client, message: Message):
    text = message.text.strip()

    # Çok satırlı veya tek satır komut desteği
    if "\n" in text:
        lines = text.split("\n")[1:]
    else:
        parts = text.split(maxsplit=1)
        lines = [parts[1]] if len(parts) > 1 else []

    if not lines:
        return await message.reply_text(
            "Kullanım:\n"
            "/ekle link [filename]\n"
            "veya\n"
            "/ekle\\nlink1\\nlink2"
        )

    status = await message.reply_text("📥 Metadata alınıyor...")

    movie_count = 0
    series_count = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        parts = line.split(maxsplit=1)
        link = parts[0]
        extra_filename = parts[1] if len(parts) > 1 else None

        try:
            api_link = pixeldrain_to_api(link)
            real_filename = extra_filename if extra_filename else await filename_from_url(api_link)
            size = "YOK"  # Her zaman "YOK"

            # metadata.py ile uyumlu şekilde filename ver
            meta = await metadata(
                filename=real_filename,
                channel=message.chat.id,
                msg_id=message.id
            )

            # Eğer metadata alınamazsa placeholder
            if not meta:
                meta = {
                    "tmdb_id": None,
                    "imdb_id": None,
                    "title": real_filename,
                    "year": 0,
                    "quality": "Bilinmiyor",
                    "media_type": "movie",
                    "poster": "",
                    "backdrop": "",
                    "logo": "",
                    "genres": [],
                    "cast": [],
                    "runtime": "",
                    "telegram": [],
                }

            telegram_obj = {
                "quality": meta.get("quality", "Bilinmiyor"),
                "id": api_link,
                "name": real_filename,
                "size": size
            }
            meta.setdefault("telegram", []).append(telegram_obj)

            # Movie / TV ayrımı
            if meta["media_type"] == "movie":
                await movie_col.insert_one(meta)
                movie_count += 1
            else:
                await series_col.insert_one(meta)
                series_count += 1

        except Exception as e:
            LOGGER.exception(e)

    await status.edit_text(
        f"✅ İşlem tamamlandı\n🎬 Film: {movie_count}\n📺 Dizi: {series_count}"
    )

# ----------------- /SİL -----------------
awaiting_confirmation = {}

@Client.on_message(filters.command("sil") & filters.private & CustomFilters.owner)
async def sil(client: Client, message: Message):
    uid = message.from_user.id

    movie_count = await movie_col.count_documents({})
    tv_count = await series_col.count_documents({})

    if movie_count == 0 and tv_count == 0:
        return await message.reply_text("ℹ️ Veritabanı zaten boş.")

    awaiting_confirmation[uid] = True

    await message.reply_text(
        f"⚠️ TÜM VERİLER SİLİNECEK ⚠️\n\n🎬 Filmler: {movie_count}\n📺 Diziler: {tv_count}\n\n"
        "Onaylamak için **Evet** yaz.\nİptal için **Hayır** yaz."
    )

@Client.on_message(filters.private & CustomFilters.owner & filters.regex("(?i)^(evet|hayır)$"))
async def sil_onay(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in awaiting_confirmation:
        return
    awaiting_confirmation.pop(uid)

    if message.text.lower() == "evet":
        m = await movie_col.count_documents({})
        t = await series_col.count_documents({})
        await movie_col.delete_many({})
        await series_col.delete_many({})
        await message.reply_text(f"✅ Silme tamamlandı\n🎬 {m} film\n📺 {t} dizi")
    else:
        await message.reply_text("❌ Silme iptal edildi.")
