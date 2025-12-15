from pyrogram import Client, filters
from Backend.helper.custom_filter import CustomFilters
from motor.motor_asyncio import AsyncIOMotorClient
import os
import asyncio

# ------------ SADECE ENV'DEN DATABASE AL ------------
db_raw = os.getenv("DATABASE", "")
db_urls = [u.strip() for u in db_raw.split(",") if u.strip()]

if len(db_urls) < 2:
    raise Exception("İkinci DATABASE bulunamadı!")

MONGO_URL = db_urls[1]

# ------------ MONGO BAĞLANTISI ------------
client = AsyncIOMotorClient(MONGO_URL)
db = None
movie_col = None
series_col = None

async def init_db():
    global db, movie_col, series_col
    if db is not None:
        return  # zaten başlatıldıysa tekrar başlatma
    db_names = await client.list_database_names()
    db = client[db_names[0]]
    movie_col = db["movie"]
    series_col = db["tv"]

# ------------ Onay Bekleyen Kullanıcıları Sakla ------------
awaiting_confirmation = {}  # user_id -> asyncio.Task

# ------------ /ekle Komutu ------------
@Client.on_message(filters.command("ekle") & filters.private & CustomFilters.owner)
async def add_link(client, message):
    if len(message.command) < 2:
        return await message.reply_text("❌ Lütfen bir link girin. Örnek: /ekle <link>")

    link = message.command[1]
    await init_db()

    updated_count = 0

    # --- MOVIE Koleksiyonunu Güncelle ---
    async for movie in movie_col.find({}):
        updated = False
        for telegram_item in movie.get("telegram", []):
            if "id" in telegram_item:
                telegram_item["id"] = link
                updated = True
        if updated:
            await movie_col.update_one({"_id": movie["_id"]}, {"$set": movie})
            updated_count += 1

    # --- TV Koleksiyonunu Güncelle ---
    async for tv_show in series_col.find({}):
        updated = False
        for season in tv_show.get("seasons", []):
            for episode in season.get("episodes", []):
                for telegram_item in episode.get("telegram", []):
                    if "id" in telegram_item:
                        telegram_item["id"] = link
                        updated = True
        if updated:
            await series_col.update_one({"_id": tv_show["_id"]}, {"$set": tv_show})
            updated_count += 1

    await message.reply_text(f"✅ Link güncellendi. Toplam {updated_count} kayıtta id değiştirildi.")

# ------------ /sil Komutu ------------
@Client.on_message(filters.command("sil") & filters.private & CustomFilters.owner)
async def request_delete(client, message):
    user_id = message.from_user.id
    await message.reply_text(
        "⚠️ Tüm veriler silinecek!\n"
        "Onaylamak için **Evet**, iptal etmek için **Hayır** yazın.\n"
        "⏱ 60 saniye içinde cevap vermezsen işlem otomatik iptal edilir."
    )

    # Eğer zaten bekliyorsa önceki timeout iptal et
    if user_id in awaiting_confirmation:
        awaiting_confirmation[user_id].cancel()

    # 60 saniye sonra otomatik iptal
    async def timeout():
        await asyncio.sleep(60)
        if user_id in awaiting_confirmation:
            awaiting_confirmation.pop(user_id, None)
            await message.reply_text("⏰ Zaman doldu, silme işlemi otomatik olarak iptal edildi.")

    task = asyncio.create_task(timeout())
    awaiting_confirmation[user_id] = task

# ------------ "Evet" veya "Hayır" Mesajı ------------
@Client.on_message(filters.private & CustomFilters.owner & filters.text)
async def handle_confirmation(client, message):
    user_id = message.from_user.id
    if user_id not in awaiting_confirmation:
        return

    text = message.text.strip().lower()

    # Timeout'u iptal et
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
            f"✅ Silme işlemi tamamlandı.\n\n"
            f"📌 Filmler silindi: {movie_count}\n"
            f"📌 Diziler silindi: {series_count}"
        )

    elif text == "hayır":
        await message.reply_text("❌ Silme işlemi iptal edildi.")
