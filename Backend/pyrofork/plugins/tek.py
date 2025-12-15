from pyrogram import Client, filters
from pyrogram.types import Message
from Backend.helper.custom_filter import CustomFilters
import os
import asyncio
import PTN
from Backend.logger import LOGGER
from motor.motor_asyncio import AsyncIOMotorClient
from your_metadata_module import metadata  # metadata fonksiyonun bulunduğu modül

# ----------------- ENV -----------------
DATABASE_RAW = os.getenv("DATABASE", "")
db_urls = [u.strip() for u in DATABASE_RAW.split(",") if u.strip() and u.strip().startswith("mongodb+srv")]

if len(db_urls) < 2:
    raise Exception("İkinci DATABASE bulunamadı!")

MONGO_URL = db_urls[1]  # ikinci database
DB_NAME = "dbFyvio"

# ----------------- Mongo Async -----------------
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]
movie_col = db["movie"]
series_col = db["tv"]

async def init_db():
    global db, movie_col, series_col
    db = client[DB_NAME]
    movie_col = db["movie"]
    series_col = db["tv"]

# ----------------- Onay Bekleyen ve Flood -----------------
awaiting_confirmation = {}
flood_wait = 30
last_command_time = {}

# ----------------- /ekle Komutu -----------------
@Client.on_message(filters.command("ekle") & filters.private & CustomFilters.owner)
async def add_file(client: Client, message: Message):
    await init_db()
    if len(message.command) < 3:
        await message.reply_text("Kullanım: /ekle <ID> <DosyaAdı>")
        return

    file_id = message.command[1]  # artık URL yerine ID
    filename = " ".join(message.command[2:])

    try:
        parsed = PTN.parse(filename)
    except Exception as e:
        await message.reply_text(f"Dosya adı ayrıştırılamadı: {e}")
        return

    title = parsed.get("title")
    season = parsed.get("season")
    episode = parsed.get("episode")
    year = parsed.get("year")
    quality = parsed.get("resolution")

    if not title:
        await message.reply_text("Başlık bulunamadı, lütfen doğru bir dosya adı girin.")
        return

    meta = await metadata(filename, message.chat.id, message.id)
    if not meta:
        await message.reply_text(f"{title} için metadata bulunamadı.")
        return

    record = {
        "title": meta.get("title", title),
        "season": season,
        "episode": episode,
        "year": meta.get("year", year),
        "quality": quality,
        "id": file_id,
        "tmdb_id": meta.get("tmdb_id"),
        "imdb_id": meta.get("imdb_id"),
        "description": meta.get("description", ""),
        "poster": meta.get("poster", ""),
        "backdrop": meta.get("backdrop", ""),
        "logo": meta.get("logo", ""),
        "genres": meta.get("genres", []),
        "media_type": meta.get("media_type"),
        "cast": meta.get("cast", []),
        "runtime": meta.get("runtime", ""),
        "episode_title": meta.get("episode_title", ""),
        "episode_backdrop": meta.get("episode_backdrop", ""),
        "episode_overview": meta.get("episode_overview", ""),
        "episode_released": meta.get("episode_released", ""),
    }

    collection = series_col if season else movie_col
    await collection.insert_one(record)
    await message.reply_text(f"✅ {title} başarıyla eklendi.")

# ----------------- /sil Komutu -----------------
@Client.on_message(filters.command("sil") & filters.private & CustomFilters.owner)
async def request_delete(client: Client, message: Message):
    user_id = message.from_user.id
    await message.reply_text(
        "⚠️ Tüm veriler silinecek!\n"
        "Onaylamak için **Evet**, iptal etmek için **Hayır** yazın.\n"
        "⏱ 60 saniye içinde cevap vermezsen işlem otomatik iptal edilir."
    )

    if user_id in awaiting_confirmation:
        awaiting_confirmation[user_id].cancel()

    async def timeout():
        await asyncio.sleep(60)
        if user_id in awaiting_confirmation:
            awaiting_confirmation.pop(user_id, None)
            await message.reply_text("⏰ Zaman doldu, silme işlemi otomatik olarak iptal edildi.")

    task = asyncio.create_task(timeout())
    awaiting_confirmation[user_id] = task

@Client.on_message(filters.private & CustomFilters.owner & filters.text)
async def handle_confirmation(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in awaiting_confirmation:
        return

    text = message.text.strip().lower()
    awaiting_confirmation[user_id].cancel()
    awaiting_confirmation.pop(user_id, None)

    await init_db()
    if text == "evet":
        movie_count = await movie_col.count_documents({})
        series_count = await series_col.count_documents({})

        await movie_col.delete_many({})
        await series_col.delete_many({})

        await message.reply_text(
            f"✅ Silme işlemi tamamlandı.\n\n"
            f"📌 Filmler silindi: {movie_count}\n"
            f"📌 Diziler silindi: {series_count}"
        )
    elif text == "hayır":
        await message.reply_text("❌ Silme işlemi iptal edildi.")
