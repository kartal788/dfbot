import os
import json
import time
import asyncio
import tempfile
import PTN

from pyrogram import Client, filters
from pyrogram.types import Message

from motor.motor_asyncio import AsyncIOMotorClient
from themoviedb import aioTMDb

from Backend.helper.custom_filter import CustomFilters
from Backend.helper.encrypt import encode_string
from Backend.logger import LOGGER

# ================= ENV =================
DATABASE_RAW = os.getenv("DATABASE", "")
DB_URLS = [u.strip() for u in DATABASE_RAW.split(",") if u.strip()]
if len(DB_URLS) < 2:
    raise Exception("İkinci DATABASE bulunamadı!")

MONGO_URL = DB_URLS[1]
TMDB_API = os.getenv("TMDB_API", "")

# ================= MONGO =================
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = None
movie_col = None
series_col = None

async def init_db():
    global db, movie_col, series_col
    if db is not None:
        return
    db_names = await mongo_client.list_database_names()
    if not db_names:
        raise Exception("MongoDB içinde veritabanı bulunamadı!")
    db = mongo_client[db_names[0]]
    movie_col = db["movie"]
    series_col = db["tv"]

# ================= TMDB =================
tmdb = aioTMDb(key=TMDB_API, language="en-US", region="US")
API_SEMAPHORE = asyncio.Semaphore(12)

# ================= GLOBAL =================
awaiting_confirmation = {}
last_command_time = {}
flood_wait = 30

# ================= HATA DOSYASI =================
async def send_error_file(client: Client, chat_id: int, error: Exception):
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(str(error))
            error_file = f.name
        await client.send_document(chat_id=chat_id, document=error_file, caption="⚠️ Hata oluştu")
        os.remove(error_file)
    except Exception as e:
        LOGGER.exception("Hata dosyası gönderilemedi")

# ================= /EKLE =================
@Client.on_message(filters.command("ekle") & filters.private & CustomFilters.owner)
async def add_file(client: Client, message: Message):
    try:
        await init_db()
        if len(message.command) < 3:
            await message.reply_text("Kullanım: /ekle <URL> <DosyaAdı>")
            return

        url = message.command[1]
        filename = " ".join(message.command[2:])

        try:
            parsed = PTN.parse(filename)
        except Exception as e:
            await message.reply_text(f"Dosya adı ayrıştırılamadı:\n{e}")
            return

        title = parsed.get("title")
        season = parsed.get("season")
        episode = parsed.get("episode")
        year = parsed.get("year")
        quality = parsed.get("resolution")

        if not title:
            await message.reply_text("Başlık bulunamadı.")
            return

        try:
            encoded_string = await encode_string({"chat_id": message.chat.id, "msg_id": message.id})
        except Exception:
            encoded_string = None

        async with API_SEMAPHORE:
            if season and episode:
                results = await tmdb.search().tv(query=title)
            else:
                results = await tmdb.search().movies(query=title, year=year)

        if not results:
            await message.reply_text(f"{title} için TMDb sonucu bulunamadı.")
            return

        meta = results[0]

        record = {
            "title": title,
            "season": season,
            "episode": episode,
            "year": year,
            "quality": quality,
            "url": url,
            "tmdb_id": getattr(meta, "id", None),
            "description": getattr(meta, "overview", ""),
            "encoded_string": encoded_string
        }

        collection = series_col if season else movie_col
        await collection.insert_one(record)
        await message.reply_text(f"✅ **{title}** eklendi.")

    except Exception as e:
        LOGGER.exception("ekle hatası")
        await send_error_file(client, message.chat.id, e)

# ================= /SIL =================
@Client.on_message(filters.command("sil") & filters.private & CustomFilters.owner)
async def request_delete(client: Client, message: Message):
    try:
        user_id = message.from_user.id
        await message.reply_text(
            "⚠️ **TÜM VERİLER SİLİNECEK**\n"
            "Onaylamak için **Evet**\n"
            "İptal için **Hayır** yazın.\n"
            "⏱ 60 saniye süreniz var."
        )

        if user_id in awaiting_confirmation:
            awaiting_confirmation[user_id].cancel()

        async def timeout():
            await asyncio.sleep(60)
            if user_id in awaiting_confirmation:
                awaiting_confirmation.pop(user_id, None)
                await message.reply_text("⏰ Süre doldu. İşlem iptal edildi.")

        awaiting_confirmation[user_id] = asyncio.create_task(timeout())

    except Exception as e:
        LOGGER.exception("sil hatası")
        await send_error_file(client, message.chat.id, e)

@Client.on_message(filters.private & CustomFilters.owner & filters.text)
async def handle_delete_confirmation(client: Client, message: Message):
    try:
        user_id = message.from_user.id
        if user_id not in awaiting_confirmation:
            return

        awaiting_confirmation[user_id].cancel()
        awaiting_confirmation.pop(user_id, None)
        await init_db()
        text = message.text.lower().strip()

        if text == "evet":
            movie_count = await movie_col.count_documents({})
            series_count = await series_col.count_documents({})
            await movie_col.delete_many({})
            await series_col.delete_many({})
            await message.reply_text(
                f"✅ **Silme tamamlandı**\n\n"
                f"🎬 Filmler: {movie_count}\n"
                f"📺 Diziler: {series_count}"
            )
        elif text == "hayır":
            await message.reply_text("❌ Silme iptal edildi.")

    except Exception as e:
        LOGGER.exception("sil onay hatası")
        await send_error_file(client, message.chat.id, e)

# ================= /VINDIR =================
@Client.on_message(filters.command("vindir") & filters.private & CustomFilters.owner)
async def download_collections(client: Client, message: Message):
    try:
        user_id = message.from_user.id
        now = time.time()
        if user_id in last_command_time and now - last_command_time[user_id] < flood_wait:
            wait = flood_wait - (now - last_command_time[user_id])
            await message.reply_text(f"⚠️ {wait:.1f} saniye bekleyin.")
            return

        last_command_time[user_id] = now
        await init_db()

        movie_data = await movie_col.find({}, {"_id": 0}).to_list(None)
        tv_data = await series_col.find({}, {"_id": 0}).to_list(None)

        if not movie_data and not tv_data:
            await message.reply_text("⚠️ Koleksiyonlar boş.")
            return

        data = {"movie": movie_data, "tv": tv_data}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2, default=str)
            file_path = tmp.name

        await client.send_document(chat_id=message.chat.id, document=file_path, caption="📁 Film ve Dizi Veritabanı")
        os.remove(file_path)

    except Exception as e:
        LOGGER.exception("vindir hatası")
        await send_error_file(client, message.chat.id, e)
