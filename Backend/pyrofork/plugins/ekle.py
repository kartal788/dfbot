# ekle.py
import json
import asyncio
from pyrogram import Client, filters
from Backend.helper.custom_filter import CustomFilters
from motor.motor_asyncio import AsyncIOMotorClient
import os

# ------------ SADECE ENV'DEN DATABASE AL ------------
db_raw = os.getenv("DATABASE", "")
db_urls = [u.strip() for u in db_raw.split(",") if u.strip()]

if len(db_urls) < 2:
    raise Exception("İkinci DATABASE bulunamadı!")

MONGO_URL = db_urls[1]

# ------------ MONGO BAĞLANTISI ------------
client_db = AsyncIOMotorClient(MONGO_URL)
db = None
movie_col = None
series_col = None

async def init_db():
    global db, movie_col, series_col
    db_names = await client_db.list_database_names()
    db = client_db[db_names[0]]
    movie_col = db["movie"]
    series_col = db["tv"]

# ------------ /ekle Komutu ------------
@Client.on_message(filters.command("ekle") & filters.private & CustomFilters.owner)
async def add_json_file(client, message):
    # Dosya yanıtı veya mesaj ile gönderilen dosya
    document = message.reply_to_message.document if message.reply_to_message else message.document

    if not document:
        await message.reply_text("⚠️ Lütfen bir .json dosyası gönderin veya yanıtlayın.")
        return

    if not document.file_name.endswith(".json"):
        await message.reply_text("❌ Dosya JSON formatında olmalı!")
        return

    # Dosyayı indir
    file_path = await client.download_media(document)
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        await message.reply_text(f"❌ JSON dosyası okunamadı: {e}")
        return

    # DB'yi başlat
    await init_db()

    added_count = {"movie": 0, "tv": 0}

    # Liste veya tek obje kontrolü
    items = data if isinstance(data, list) else [data] if isinstance(data, dict) else None

    if not items:
        await message.reply_text("❌ JSON formatı doğru değil, obje veya liste olmalı.")
        return

    for item in items:
        item_type = item.get("type", "").lower()
        if item_type == "movie":
            await movie_col.insert_one(item)
            added_count["movie"] += 1
        elif item_type in {"series", "tv"}:
            await series_col.insert_one(item)
            added_count["tv"] += 1
        else:
            # type alanı yoksa default olarak movie ekle
            await movie_col.insert_one(item)
            added_count["movie"] += 1

    await message.reply_text(
        f"✅ JSON verisi başarıyla veritabanına eklendi.\n"
        f"📌 Filmler: {added_count['movie']}\n"
        f"📌 Diziler: {added_count['tv']}"
    )
