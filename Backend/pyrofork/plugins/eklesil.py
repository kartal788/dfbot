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

# ===================== CONFIG =====================
DATABASE_RAW = os.getenv("DATABASE", "")
db_urls = [u.strip() for u in DATABASE_RAW.split(",") if u.strip().startswith("mongodb+srv")]
MONGO_URL = db_urls[1]
DB_NAME = "dbFyvio"

TMDB_API = os.getenv("TMDB_API", "")
tmdb = aioTMDb(key=TMDB_API, language="en-US", region="US")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]
movie_col = db["movie"]
series_col = db["tv"]

API_SEMAPHORE = asyncio.Semaphore(12)
awaiting_confirmation = {}

# ===================== HELPERS =====================
def pixeldrain_to_api(url):
    m = re.match(r"https?://pixeldrain\.com/u/([a-zA-Z0-9]+)", url)
    return f"https://pixeldrain.com/api/file/{m.group(1)}" if m else url


async def head(url, key):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.head(url, allow_redirects=True) as r:
                return r.headers.get(key)
    except:
        return None


async def filename_from_url(url):
    cd = await head(url, "Content-Disposition")
    if cd:
        m = re.search(r'filename="(.+?)"', cd)
        if m:
            return m.group(1)
    return url.split("/")[-1]


async def filesize(url):
    size = await head(url, "Content-Length")
    if not size:
        return None

    size = int(size)
    for u in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.2f} {u}"
        size /= 1024


def parse_links_and_names(text: str):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    items = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("/ekle"):
            line = line.replace("/ekle", "", 1).strip()
            if not line:
                i += 1
                continue

        if line.startswith("http"):
            parts = line.split(maxsplit=1)
            url = parts[0]
            name = parts[1] if len(parts) == 2 else None

            if not name and i + 1 < len(lines) and not lines[i + 1].startswith("http"):
                name = lines[i + 1]
                i += 1

            items.append((pixeldrain_to_api(url), name))

        i += 1

    return items


def year_from(date):
    try:
        return int(str(date).split("-")[0])
    except:
        return None


def build_media_record(meta, details, filename, url, quality, media_type, season=None, episode=None):
    base = {
        "tmdb_id": meta.id,
        "title": meta.title if media_type == "movie" else meta.name,
        "description": meta.overview or "",
        "rating": meta.vote_average or 0,
        "release_year": year_from(meta.release_date if media_type == "movie" else meta.first_air_date),
        "updated_on": str(datetime.utcnow()),
    }

    if media_type == "movie":
        return {
            **base,
            "media_type": "movie",
            "telegram": [{
                "quality": quality,
                "id": url,
                "name": filename,
                "size": "YOK"
            }]
        }

    return {
        **base,
        "media_type": "tv",
        "seasons": [{
            "season_number": season,
            "episodes": [{
                "episode_number": episode,
                "title": filename,
                "telegram": [{
                    "quality": quality,
                    "id": url,
                    "name": filename,
                    "size": "YOK"
                }]
            }]
        }]
    }

# ===================== /EKLE =====================
@Client.on_message(filters.command("ekle") & filters.private & CustomFilters.owner)
async def ekle(client: Client, message: Message):
    items = parse_links_and_names(message.text)
    if not items:
        return await message.reply_text("Kullanım:\n/ekle link [dosya_adi.mkv]")

    success, failed = [], []

    for raw, custom_name in items:
        try:
            filename = custom_name or await filename_from_url(raw)
            parsed = PTN.parse(filename)

            title = parsed.get("title")
            season = parsed.get("season")
            episode = parsed.get("episode")
            year = parsed.get("year")
            quality = parsed.get("resolution") or "UNKNOWN"
            size = await filesize(raw) or "YOK"

            async with API_SEMAPHORE:
                if season and episode:
                    results = await tmdb.search().tv(query=title)
                    col = series_col
                    media_type = "tv"
                else:
                    results = await tmdb.search().movies(query=title, year=year)
                    col = movie_col
                    media_type = "movie"

            if not results:
                raise Exception("TMDB bulunamadı")

            meta = results[0]
            details = await (tmdb.tv(meta.id).details() if media_type == "tv" else tmdb.movie(meta.id).details())

            doc = await col.find_one({"tmdb_id": meta.id})
            if not doc:
                doc = build_media_record(meta, details, filename, raw, quality, media_type, season, episode)
                doc["telegram" if media_type == "movie" else "seasons"][0]["telegram"][0]["size"] = size
                await col.insert_one(doc)
            else:
                doc["updated_on"] = str(datetime.utcnow())
                await col.replace_one({"_id": doc["_id"]}, doc)

            success.append(filename)
        except:
            failed.append(filename)

    await message.reply_text(
        f"✅ Başarılı: {len(success)}\n❌ Başarısız: {len(failed)}"
    )

# ===================== /SİL =====================
@Client.on_message(filters.command("sil") & filters.private & CustomFilters.owner)
async def sil(client: Client, message: Message):
    uid = message.from_user.id
    awaiting_confirmation[uid] = True

    await message.reply_text(
        "⚠️ **TÜM VERİLER SİLİNECEK!**\n\n"
        "Onay için **Evet**, iptal için **Hayır** yaz."
    )


@Client.on_message(filters.private & CustomFilters.owner & filters.regex("(?i)^(evet|hayır)$"))
async def sil_onay(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in awaiting_confirmation:
        return

    awaiting_confirmation.pop(uid)

    if message.text.lower() == "evet":
        await movie_col.delete_many({})
        await series_col.delete_many({})
        await message.reply_text("🗑 Tüm veriler silindi.")
    else:
        await message.reply_text("❌ İşlem iptal edildi.")
