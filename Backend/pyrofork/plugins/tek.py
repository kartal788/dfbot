import os
import re
import asyncio
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient
from themoviedb import aioTMDb
import PTN
import aiohttp
from Backend.helper.custom_filter import CustomFilters

# ----------------- ENV -----------------
DATABASE_RAW = os.getenv("DATABASE", "")
db_urls = [u.strip() for u in DATABASE_RAW.split(",") if u.strip().startswith("mongodb")]
if not db_urls:
    raise RuntimeError("MongoDB URL bulunamadı")

MONGO_URL = db_urls[0]
DB_NAME = "dbFyvio"

TMDB_API = os.getenv("TMDB_API", "")
tmdb = aioTMDb(key=TMDB_API, language="tr-TR", region="TR")

# ----------------- MongoDB -----------------
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]
movie_col = db["movie"]
series_col = db["tv"]

API_SEMAPHORE = asyncio.Semaphore(10)
awaiting_confirmation = {}

session = aiohttp.ClientSession()

# ----------------- Helpers -----------------
def safe(obj, attr, default=None):
    return getattr(obj, attr, default) or default

def year_from(date):
    try:
        return int(str(date).split("-")[0])
    except:
        return None

def pixeldrain_to_api(url):
    m = re.match(r"https?://pixeldrain\.com/u/([a-zA-Z0-9]+)", url)
    return f"https://pixeldrain.com/api/file/{m.group(1)}" if m else url

async def head(url, key):
    try:
        async with session.head(url, allow_redirects=True) as r:
            return r.headers.get(key)
    except:
        return None

async def filesize(url):
    size = await head(url, "Content-Length")
    if not size:
        return "UNKNOWN"
    size = int(size)
    for u in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.2f}{u}"
        size /= 1024

def episode_backdrop(imdb_id, season, episode):
    return f"https://episodes.metahub.space/{imdb_id}/{season}/{episode}/w780.jpg"

# ----------------- BUILDERS -----------------
def build_movie(meta, details, filename, url, quality, size):
    return {
        "tmdb_id": meta.id,
        "imdb_id": safe(meta, "imdb_id"),
        "title": safe(meta, "title"),
        "description": safe(meta, "overview", ""),
        "rating": safe(meta, "vote_average", 0),
        "release_year": year_from(safe(meta, "release_date")),
        "poster": f"https://image.tmdb.org/t/p/w500{safe(meta,'poster_path','')}",
        "backdrop": f"https://image.tmdb.org/t/p/w780{safe(meta,'backdrop_path','')}",
        "runtime": f"{safe(details,'runtime','UNKNOWN')} min",
        "media_type": "movie",
        "updated_on": str(datetime.utcnow()),
        "telegram": [{
            "quality": quality,
            "id": url,
            "name": filename,
            "size": size
        }]
    }

def build_episode(meta, episode_details, season, episode, filename, url, quality, size):
    return {
        "episode_number": episode,
        "title": filename,  # DOSYA ADI BİREBİR
        "episode_backdrop": episode_backdrop(meta.imdb_id, season, episode),
        "overview": safe(episode_details, "overview", ""),
        "released": (
            f"{episode_details.air_date}T08:00:00.000Z"
            if safe(episode_details, "air_date")
            else None
        ),
        "telegram": [{
            "quality": quality,
            "id": url,
            "name": filename,
            "size": size
        }]
    }

# ----------------- /EKLE -----------------
@Client.on_message(filters.command("ekle") & filters.private & CustomFilters.owner)
async def ekle(client: Client, message: Message):
    args = message.command[1:]
    if not args:
        return await message.reply_text("Kullanım: /ekle link1 [link2 ...]")

    added = set()

    for raw_url in args:
        url = pixeldrain_to_api(raw_url)
        filename = raw_url.split("/")[-1]
        try:
            parsed = PTN.parse(filename)
        except:
            continue

        title = parsed.get("title")
        season = parsed.get("season")
        episode = parsed.get("episode")
        year = parsed.get("year")
        quality = parsed.get("resolution") or "UNKNOWN"
        size = await filesize(url)

        async with API_SEMAPHORE:
            if season and episode:
                results = await tmdb.search().tv(query=title)
                media_type = "tv"
                col = series_col
            else:
                results = await tmdb.search().movies(query=title, year=year)
                media_type = "movie"
                col = movie_col

        if not results:
            continue

        meta = results[0]

        if media_type == "movie":
            details = await tmdb.movie(meta.id).details()
            doc = await col.find_one({"tmdb_id": meta.id})

            if not doc:
                doc = build_movie(meta, details, filename, url, quality, size)
                await col.insert_one(doc)
            else:
                doc["telegram"].append({
                    "quality": quality,
                    "id": url,
                    "name": filename,
                    "size": size
                })
                await col.replace_one({"tmdb_id": meta.id}, doc)

            added.add(meta.title)

        else:
            details = await tmdb.tv(meta.id).details()
            episode_details = await tmdb.tv(meta.id).season(season).episode(episode).details()
            doc = await col.find_one({"tmdb_id": meta.id})

            episode_obj = build_episode(
                meta, episode_details, season, episode,
                filename, url, quality, size
            )

            if not doc:
                doc = {
                    "tmdb_id": meta.id,
                    "imdb_id": meta.imdb_id,
                    "title": meta.name,
                    "description": safe(meta, "overview", ""),
                    "rating": safe(meta, "vote_average", 0),
                    "release_year": year_from(meta.first_air_date),
                    "poster": f"https://image.tmdb.org/t/p/w500{meta.poster_path}",
                    "backdrop": f"https://image.tmdb.org/t/p/w780{meta.backdrop_path}",
                    "media_type": "tv",
                    "updated_on": str(datetime.utcnow()),
                    "seasons": [{
                        "season_number": season,
                        "episodes": [episode_obj]
                    }]
                }
                await col.insert_one(doc)
            else:
                s = next((x for x in doc["seasons"] if x["season_number"] == season), None)
                if not s:
                    s = {"season_number": season, "episodes": []}
                    doc["seasons"].append(s)

                e = next((x for x in s["episodes"] if x["episode_number"] == episode), None)
                if not e:
                    s["episodes"].append(episode_obj)
                else:
                    e["telegram"].append(episode_obj["telegram"][0])

                await col.replace_one({"tmdb_id": meta.id}, doc)

            added.add(meta.name)

    await message.reply_text(
        "✅ Eklendi:\n" + "\n".join(added) if added else "⚠️ İçerik eklenemedi."
    )

# ----------------- /SİL -----------------
@Client.on_message(filters.command("sil") & filters.private & CustomFilters.owner)
async def sil(client: Client, message: Message):
    uid = message.from_user.id
    awaiting_confirmation[uid] = True
    await message.reply_text("⚠️ TÜM VERİLER SİLİNECEK!\nOnay için **Evet**, iptal için **Hayır** yaz.")

@Client.on_message(
    filters.private & CustomFilters.owner & filters.regex("^(Evet|Hayır)$")
)
async def sil_onay(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in awaiting_confirmation:
        return

    awaiting_confirmation.pop(uid)

    if message.text.lower() == "evet":
        await movie_col.delete_many({})
        await series_col.delete_many({})
        await message.reply_text("✅ Tüm veriler silindi.")
    else:
        await message.reply_text("❌ İşlem iptal edildi.")
