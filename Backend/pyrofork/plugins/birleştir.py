from pyrogram import Client, filters
from Backend.helper.custom_filter import CustomFilters
from Backend.helper import metadata as md_helper
from motor.motor_asyncio import AsyncIOMotorClient
import os
import requests
import asyncio
from urllib.parse import urlparse

PIXELDRAIN_API_KEY = os.getenv("PIXELDRAIN")
db_raw = os.getenv("DATABASE", "")
db_urls = [u.strip() for u in db_raw.split(",") if u.strip()]

if len(db_urls) < 2:
    raise Exception("İkinci DATABASE bulunamadı!")

MONGO_URL = db_urls[1]

client_db = AsyncIOMotorClient(MONGO_URL)
db = client_db.get_database()
movie_col = db["movie"]
series_col = db["tv"]

awaiting_confirmation = {}  # /sil onay bekleyenler: user_id -> asyncio.Task

async def init_db():
    global db, movie_col, series_col
    return  # zaten başlatıldı

def get_pixeldrain_filename(url: str) -> str | None:
    """Pixeldrain API ile dosya adını alır."""
    if not PIXELDRAIN_API_KEY:
        return None

    parsed = urlparse(url)
    file_id = parsed.path.strip("/").split("/")[-1]
    if not file_id:
        return None

    api_url = f"https://pixeldrain.com/api/file/{file_id}"
    headers = {"Authorization": f"Bearer {PIXELDRAIN_API_KEY}"}

    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("name")
    except Exception:
        return None

# ----------------- /ekle -----------------
@Client.on_message(filters.command("ekle") & filters.private & CustomFilters.owner)
async def add_link(client, message):
    if len(message.command) < 2:
        return await message.reply_text("❌ Lütfen bir link girin. Örnek: /ekle <link>")

    url = message.command[1]
    await init_db()

    # --- Dosya adını alma ---
    filename = get_pixeldrain_filename(url)
    if not filename:
        if len(message.text.split()) >= 3:
            filename = message.text.split(None, 2)[2]
        else:
            return await message.reply_text("❌ Dosya adı alınamadı. Linki kontrol edin veya API key eksik.")

    # --- Metadata çekme ---
    try:
        meta = await md_helper.metadata(filename, channel=message.chat.id, msg_id=message.id)
        if not meta:
            return await message.reply_text("❌ Metadata alınamadı.")
    except Exception as e:
        return await message.reply_text(f"❌ Metadata hatası: {e}")

    # --- DB İşleme ---
    col = movie_col if meta["media_type"] == "movie" else series_col
    query = {"imdb_id": meta.get("imdb_id")} if meta.get("imdb_id") else {"tmdb_id": meta.get("tmdb_id")}

    # Daha önce varsa güncelle, yoksa ekle
    existing = await col.find_one(query)
    if existing:
        # Telegram linki güncelle
        existing_telegram = existing.get("telegram", [])
        found = False
        for t in existing_telegram:
            if "id" in t:
                t["id"] = filename
                found = True
        if not found:
            existing_telegram.append({"id": filename})
        await col.update_one({"_id": existing["_id"]}, {"$set": existing})
        await message.reply_text(f"✅ Kayıt güncellendi: {filename}")
    else:
        meta["telegram"] = [{"id": filename}]
        await col.insert_one(meta)
        await message.reply_text(f"✅ Yeni kayıt eklendi: {filename}")

# ----------------- /sil -----------------
@Client.on_message(filters.command("sil") & filters.private & CustomFilters.owner)
async def request_delete(client, message):
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
            await message.reply_text("⏰ Zaman doldu, silme işlemi iptal edildi.")

    task = asyncio.create_task(timeout())
    awaiting_confirmation[user_id] = task

@Client.on_message(filters.private & CustomFilters.owner & filters.text)
async def handle_confirmation(client, message):
    user_id = message.from_user.id
    if user_id not in awaiting_confirmation:
        return

    text = message.text.strip().lower()
    awaiting_confirmation[user_id].cancel()
    awaiting_confirmation.pop(user_id, None)

    if text == "evet":
        await message.reply_text("🗑️ Silme işlemi başlatılıyor...")
        await init_db()
        movie_count = await movie_col.count_documents({})
        series_count = await series_col.count_documents({})
        await movie_col.delete_many({})
        await series_col.delete_many({})
        await message.reply_text(
            f"✅ Silme tamamlandı.\n📌 Filmler: {movie_count}\n📌 Diziler: {series_count}"
        )
    elif text == "hayır":
        await message.reply_text("❌ Silme iptal edildi.")
