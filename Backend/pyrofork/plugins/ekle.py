from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from Backend.helper.database import Database
from Backend.helper.metadata import metadata
from Backend.config import Telegram
from Backend.logger import LOGGER
import re

bot = Bot(token=Telegram.BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

db = Database()
await db.connect()

# ------------------ /ekle ------------------
@dp.message_handler(commands=["ekle"])
async def cmd_add(message: types.Message):
    args = message.get_args()
    if not args:
        await message.reply("Lütfen link veya dosya adını girin.")
        return

    # Örnek: link ve dosya adını ayırma
    match = re.search(r"(?:https?://\S+)\s+(.+)", args)
    filename = match.group(1).strip() if match else args.strip()

    await message.reply(f"Metadata alınıyor: <b>{filename}</b>...")
    data = await metadata(filename, message.chat.id, message.message_id)

    if not data:
        await message.reply("Metadata alınamadı.")
        return

    try:
        # Mevcut Database sınıfındaki insert_media metodunu kullanıyoruz
        result = await db.insert_media(
            metadata_info=data,
            channel=message.chat.id,
            msg_id=message.message_id,
            size=data.get("size", "Unknown"),
            name=filename
        )

        if result:
            await message.reply(f"Dosya başarıyla eklendi: <b>{data.get('title')}</b>")
        else:
            await message.reply("Dosya eklenirken bir hata oluştu.")

    except Exception as e:
        LOGGER.error(f"/ekle komutu hata: {e}")
        await message.reply("Dosya eklenirken bir hata oluştu.")

# ------------------ /sil ------------------
@dp.message_handler(commands=["sil"])
async def cmd_delete(message: types.Message):
    args = message.get_args().strip()
    if not args:
        await message.reply("Lütfen silinecek dosya adını veya TMDB/IMDB ID girin.")
        return

    # Metadata'dan tmdb_id alınabilir veya direkt args kullanılabilir
    tmdb_id = None
    media_type = None

    # Eğer numeric ise tmdb_id kabul edelim
    if args.isdigit():
        tmdb_id = int(args)
        # Medya tipini DB'den bul
        for collection in ["movie", "tv"]:
            doc = await db.dbs[f"storage_{db.current_db_index}"][collection].find_one({"tmdb_id": tmdb_id})
            if doc:
                media_type = "Movie" if collection == "movie" else "TV"
                break
    else:
        await message.reply("Lütfen TMDB ID giriniz.")
        return

    if not tmdb_id or not media_type:
        await message.reply(f"{args} bulunamadı.")
        return

    try:
        deleted = await db.delete_document(media_type, tmdb_id, db.current_db_index)
        if deleted:
            await message.reply(f"{media_type} başarıyla silindi: <b>{tmdb_id}</b>")
        else:
            await message.reply(f"{media_type} bulunamadı: <b>{tmdb_id}</b>")
    except Exception as e:
        LOGGER.error(f"/sil komutu hata: {e}")
        await message.reply("Dosya silinirken hata oluştu.")

if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
