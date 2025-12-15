from pyrogram import Client, filters
from Backend.helper.custom_filter import CustomFilters
from Backend.helper.database import Database
from Backend.helper.modal import MovieSchema, TVShowSchema, QualityDetail, Season, Episode
from datetime import datetime

@Client.on_message(filters.command("ekle") & filters.private & CustomFilters.owner)
async def add_file_direct(client, message):
    if len(message.command) < 4:
        await message.reply_text("⚠️ Kullanım: `/ekle <movie|tv> <tmdb_id> <dosya_link>`")
        return

    media_type_input = message.command[1].lower()
    tmdb_id = int(message.command[2])
    file_link = message.command[3]
    file_name = file_link.split("/")[-1]
    file_size = "unknown"

    db = Database()
    await db.connect()

    try:
        if media_type_input == "movie":
            schema = MovieSchema(
                tmdb_id=tmdb_id,
                imdb_id=None,
                db_index=db.current_db_index,
                title=f"Movie {tmdb_id}",
                genres=[],
                description="",
                rating=None,
                release_year=None,
                poster=None,
                backdrop=None,
                logo=None,
                cast=[],
                runtime=None,
                media_type="movie",
                telegram=[QualityDetail(
                    quality="default",
                    id=file_link,
                    name=file_name,
                    size=file_size
                )]
            )
            result = await db.update_movie(schema)
            media_type = "Movie"

        elif media_type_input == "tv":
            season = Season(
                season_number=1,
                episodes=[Episode(
                    episode_number=1,
                    title=f"Episode 1",
                    episode_backdrop=None,
                    overview="",
                    released=None,
                    telegram=[QualityDetail(
                        quality="default",
                        id=file_link,
                        name=file_name,
                        size=file_size
                    )]
                )]
            )
            schema = TVShowSchema(
                tmdb_id=tmdb_id,
                imdb_id=None,
                db_index=db.current_db_index,
                title=f"TV Show {tmdb_id}",
                genres=[],
                description="",
                rating=None,
                release_year=None,
                poster=None,
                backdrop=None,
                logo=None,
                cast=[],
                runtime=None,
                media_type="tv",
                seasons=[season]
            )
            result = await db.update_tv_show(schema)
            media_type = "TV Show"

        else:
            await message.reply_text("⚠️ Media type `movie` veya `tv` olmalı.")
            return

        if result:
            await message.reply_text(f"✅ {media_type} veritabanına kaydedildi / güncellendi\nTMDB ID: `{tmdb_id}`\nDosya: `{file_name}`")
        else:
            await message.reply_text("⚠️ Kayıt başarısız oldu.")

    except Exception as e:
        await message.reply_text(f"❌ Hata:\n`{e}`")
    finally:
        await db.disconnect()
