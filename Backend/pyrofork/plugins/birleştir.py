from pyrogram import Client, filters
from pyrogram.types import Message
from Backend.helper.database import Database
from Backend.logger import LOGGER

# Database nesnesi
db = Database()

# Async init fonksiyonu
async def init_db():
    await db.connect()
    LOGGER.info("Database initialized for medya plugin")

# -----------------------------
# /ekle Komutu
# -----------------------------
@Client.on_message(filters.command("ekle") & filters.private)
async def ekle_handler(client: Client, message: Message):
    """
    /ekle komutu ile medya ekleme
    Komut örneği:
    /ekle media_type=movie tmdb_id=12345 title=MovieName quality=1080p size=1GB name=filename
    /ekle media_type=tv tmdb_id=54321 season_number=1 episode_number=2 episode_title=E1 quality=1080p size=1GB name=filename
    """
    try:
        text = message.text
        args = {}
        for part in text.split()[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                args[key] = value

        media_type = args.get("media_type")
        if not media_type:
            await message.reply("❌ media_type belirtilmemiş.")
            return

        # DB’ye ekleme
        result_id = await db.insert_media(args, channel=message.chat.id, msg_id=message.message_id, size=args.get("size", ""), name=args.get("name", ""))
        if result_id:
            await message.reply(f"✅ {media_type} başarıyla eklendi. ID: {result_id}")
        else:
            await message.reply(f"❌ {media_type} eklenemedi.")

    except Exception as e:
        LOGGER.error(f"/ekle komut hatası: {e}")
        await message.reply(f"❌ Hata oluştu: {e}")


# -----------------------------
# /sil Komutu
# -----------------------------
@Client.on_message(filters.command("sil") & filters.private)
async def sil_handler(client: Client, message: Message):
    """
    /sil komutu ile medya silme
    Komut örneği:
    /sil media_type=movie tmdb_id=12345
    /sil media_type=tv tmdb_id=54321 season_number=1 episode_number=2
    /sil media_type=tv tmdb_id=54321 season_number=1
    /sil media_type=tv tmdb_id=54321 season_number=1 episode_number=2 id=encoded_string
    """
    try:
        text = message.text
        args = {}
        for part in text.split()[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                args[key] = value

        media_type = args.get("media_type")
        tmdb_id = int(args.get("tmdb_id", 0))
        db_index = int(args.get("db_index", 1))  # Opsiyonel

        if media_type == "movie":
            success = await db.delete_document("Movie", tmdb_id, db_index)
            await message.reply(f"{'✅ Silindi' if success else '❌ Bulunamadı'}: Movie tmdb_id={tmdb_id}")

        elif media_type == "tv":
            season_number = int(args.get("season_number")) if "season_number" in args else None
            episode_number = int(args.get("episode_number")) if "episode_number" in args else None
            id = args.get("id")

            if id and season_number and episode_number:
                success = await db.delete_tv_quality(tmdb_id, db_index, season_number, episode_number, id)
                msg = f"{'✅ Silindi' if success else '❌ Bulunamadı'}: TV episode quality"
            elif season_number and episode_number:
                success = await db.delete_tv_episode(tmdb_id, db_index, season_number, episode_number)
                msg = f"{'✅ Silindi' if success else '❌ Bulunamadı'}: TV episode"
            elif season_number:
                success = await db.delete_tv_season(tmdb_id, db_index, season_number)
                msg = f"{'✅ Silindi' if success else '❌ Bulunamadı'}: TV season"
            else:
                success = await db.delete_document("TV", tmdb_id, db_index)
                msg = f"{'✅ Silindi' if success else '❌ Bulunamadı'}: TV show"

            await message.reply(msg)

        else:
            await message.reply("❌ media_type belirtilmemiş veya geçersiz.")

    except Exception as e:
        LOGGER.error(f"/sil komut hatası: {e}")
        await message.reply(f"❌ Hata oluştu: {e}")
