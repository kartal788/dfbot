import os
import json
import time
import asyncio
import tempfile
import PTN

from pyrogram import Client, filters
from pyrogram.types import Message
from pymongo import MongoClient
from themoviedb import aioTMDb
# Bu satırın çalışabilmesi için dosyanın ve içindeki CustomFilters sınıfının tanımlı olması gerekir.
from Backend.helper.custom_filter import CustomFilters 

# ================= ENV (Ortam Değişkenleri) =================
DATABASE_RAW = os.getenv("DATABASE", "")
DB_URLS = [u.strip() for u in DATABASE_RAW.split(",") if u.strip()]

# İkinci veritabanı adresi MONGO_URL olarak kullanılır.
MONGO_URL = DB_URLS[1] if len(DB_URLS) >= 2 else None
TMDB_API = os.getenv("TMDB_API", "")

# ================= MONGO (Veritabanı Bağlantısı) =================
mongo_client = None
db = None
movie_col = None
series_col = None

def init_db():
    """MongoDB bağlantısını başlatır ve koleksiyonları ayarlar."""
    global mongo_client, db, movie_col, series_col
    if db is not None:
        return

    if not MONGO_URL:
        raise Exception("MONGO_URL ortam değişkeni bulunamadı. Lütfen DATABASE değişkenini kontrol edin.")
        
    mongo_client = MongoClient(MONGO_URL)
    db_names = mongo_client.list_database_names()
    
    if not db_names:
        raise Exception("MongoDB içinde veritabanı bulunamadı!")
        
    db = mongo_client[db_names[0]]
    movie_col = db["movie"]
    series_col = db["tv"]

# ================= TMDB (The Movie Database) =================
tmdb = aioTMDb(key=TMDB_API, language="en-US", region="US") if TMDB_API else None
API_SEMAPHORE = asyncio.Semaphore(12)

# ================= GLOBAL (Genel Değişkenler) =================
# Silme onayı bekleyen kullanıcıları takip eder.
awaiting_confirmation = {}
# Flood koruması için komut zamanlarını takip eder.
last_command_time = {}
flood_wait = 30 # Saniye

# ================= /EKLE (Veri Ekleme) =================
@Client.on_message(filters.command("ekle") & filters.private)
async def add_file(client: Client, message: Message):
    """Verilen URL ve DosyaAdı ile bir kaydı veritabanına ekler."""
    try:
        init_db()
        if len(message.command) < 3:
            await message.reply_text("Kullanım: `/ekle <URL> <DosyaAdı>`")
            return

        url = message.command[1]
        filename = " ".join(message.command[2:])
        parsed = PTN.parse(filename)
        
        title = parsed.get("title")
        season = parsed.get("season")
        episode = parsed.get("episode")
        year = parsed.get("year")
        quality = parsed.get("resolution")

        if not title:
            await message.reply_text("Başlık (`title`) bulunamadı.")
            return

        meta = None
        if tmdb:
            async with API_SEMAPHORE:
                if season and episode:
                    results = await tmdb.search().tv(query=title)
                else:
                    results = await tmdb.search().movies(query=title, year=year)
            meta = results[0] if results else None
        
        record = {
            "title": title,
            "season": season,
            "episode": episode,
            "year": year,
            "quality": quality,
            "id": url,
            "tmdb_id": getattr(meta, "id", None) if meta else None,
            "description": getattr(meta, "overview", "") if meta else "",
        }

        collection = series_col if season else movie_col
        collection.insert_one(record)
        
        type_str = "Dizi Bölümü" if season and episode else "Film" if not season else "Dizi"
        await message.reply_text(f"✅ **{title}** ({type_str}) başarıyla eklendi.")

    except Exception as e:
        await message.reply_text(f"❌ Hata: `{e}`")

# ================= /SIL (Tüm Verileri Silme İsteği) =================
@Client.on_message(filters.command("sil") & filters.private)
async def request_delete(client: Client, message: Message):
    """Kullanıcıdan tüm verileri silmek için onay ister ve zamanlayıcı başlatır."""
    try:
        init_db()
        user_id = message.from_user.id
        
        if user_id in awaiting_confirmation:
            awaiting_confirmation[user_id].cancel()

        await message.reply_text(
            "⚠️ **TÜM VERİLER SİLİNECEK (Film ve Dizi)**\n"
            "Onaylamak için **Evet**\n"
            "İptal için **Hayır** yazın.\n"
            "⏱ 60 saniye süreniz var."
        )

        async def timeout():
            await asyncio.sleep(60)
            if user_id in awaiting_confirmation:
                awaiting_confirmation.pop(user_id, None)
                try:
                    await client.send_message(message.chat.id, "⏰ Süre doldu. İşlem iptal edildi.")
                except:
                    pass

        awaiting_confirmation[user_id] = asyncio.create_task(timeout())

    except Exception as e:
        await message.reply_text(f"❌ Hata: `{e}`")

@Client.on_message(filters.private & filters.text)
async def handle_delete_confirmation(client: Client, message: Message):
    """Silme onayını veya iptalini işler."""
    try:
        user_id = message.from_user.id
        if user_id not in awaiting_confirmation:
            return

        # Zamanlayıcıyı iptal et
        awaiting_confirmation[user_id].cancel()
        awaiting_confirmation.pop(user_id, None)
        init_db()
        text = message.text.lower().strip()

        if text == "evet":
            movie_count = movie_col.count_documents({})
            series_count = series_col.count_documents({})
            
            movie_col.delete_many({})
            series_col.delete_many({})
            
            await message.reply_text(
                f"✅ **Silme tamamlandı**\n\n"
                f"🎬 Filmler: {movie_count}\n"
                f"📺 Diziler: {series_count}"
            )
        elif text == "hayır":
            await message.reply_text("❌ Silme iptal edildi.")

    except Exception as e:
        await message.reply_text(f"❌ Hata: `{e}`")

# ================= /VINDIR (Veritabanını İndirme) =================
def export_collections_to_json(url):
    """Verilen MongoDB URL'sindeki tüm koleksiyonları JSON formatına aktarır."""
    try:
        client = MongoClient(url)
        db_name_list = client.list_database_names()
        
        if not db_name_list:
            return None

        db = client[db_name_list[0]]
        # _id hariç tüm veriyi getir
        movie_data = list(db["movie"].find({}, {"_id": 0}))
        tv_data = list(db["tv"].find({}, {"_id": 0}))

        return {"movie": movie_data, "tv": tv_data}
    except Exception as e:
        print(f"Veritabanı dışa aktarma hatası: {e}")
        return None

# CustomFilters.owner filtresi bu komutun sadece bot sahibi tarafından kullanılmasını sağlar.
@Client.on_message(filters.command("vindir") & filters.private & CustomFilters.owner)
async def vindir_command(client: Client, message: Message):
    """Veritabanındaki film ve dizi koleksiyonlarını JSON dosyası olarak gönderir."""
    user_id = message.from_user.id
    now = time.time()

    # Flood Koruması
    if user_id in last_command_time and now - last_command_time[user_id] < flood_wait:
        wait = flood_wait - (now - last_command_time[user_id])
        await message.reply_text(f"⚠️ **Flood Koruması**: Lütfen {wait:.1f} saniye bekleyin.")
        return
    last_command_time[user_id] = now

    try:
        if not MONGO_URL:
             await message.reply_text("⚠️ İkinci veritabanı adresi (MONGO_URL) bulunamadı.")
             return

        # Blocking olan dışa aktarma işlemini async yapıyı engellememek için ayrı bir thread'de çalıştır.
        await message.reply_text("⏳ Veritabanı verileri dışa aktarılıyor...")
        combined_data = await asyncio.to_thread(export_collections_to_json, MONGO_URL)
        
        if not combined_data or (not combined_data.get("movie") and not combined_data.get("tv")):
            await message.reply_text("⚠️ Koleksiyonlar boş veya veritabanı dışa aktarılamadı.")
            return

        # Geçici dosya oluşturma ve yazma
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
        tmp_file_path = tmp_file.name
        
        try:
            json.dump(combined_data, tmp_file, ensure_ascii=False, indent=2, default=str)
            tmp_file.close()

            # Dosyayı Telegram'a gönderme
            await client.send_document(
                chat_id=message.chat.id,
                document=tmp_file_path,
                caption="📁 **Film ve Dizi Koleksiyonları**\n\n*Veritabanı yedeği.*"
            )
            await message.reply_text("✅ Veritabanı başarıyla gönderildi.")
            
        finally:
            # Geçici dosyayı silme
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

    except Exception as e:
        await message.reply_text(f"❌ Hata: `{e}`")
