from fastapi import APIRouter, HTTPException
from typing import Optional
from urllib.parse import unquote
from Backend.config import Telegram
from Backend import db, __version__
from datetime import datetime, timezone, timedelta
import PTN

# ---------------- Configuration ----------------
BASE_URL = Telegram.BASE_URL
ADDON_NAME = "Arşivim"
ADDON_VERSION = __version__
PAGE_SIZE = 15

router = APIRouter(prefix="/stremio", tags=["Stremio Addon"])

# ---------------- Genres ----------------
GENRES = [
    "Aile", "Aksiyon", "Aksiyon ve Macera", "Animasyon", "Belgesel",
    "Bilim Kurgu", "Bilim Kurgu ve Fantazi", "Biyografi", "Çocuklar",
    "Dram", "Fantastik", "Gerilim", "Gerçeklik", "Gizem", "Haberler",
    "Kara Film", "Komedi", "Korku", "Kısa", "Macera", "Müzik",
    "Müzikal", "Oyun Gösterisi", "Pembe Dizi", "Romantik", "Savaş",
    "Savaş ve Politika", "Spor", "Suç", "TV Filmi", "Talk-Show",
    "Tarih", "Vahşi Batı", "Tabii", "Disney", "Netflix", "Max",
    "Amazon", "Exxen", "Gain", "Tv+", "Tod"
]

# ---------------- Helpers ----------------
def convert_to_stremio_meta(item: dict) -> dict:
    media_type = "series" if item.get("media_type") == "tv" else "movie"
    stremio_id = f"{item.get('tmdb_id')}-{item.get('db_index')}"

    return {
        "id": stremio_id,
        "type": media_type,
        "name": item.get("title"),
        "poster": item.get("poster") or "",
        "logo": item.get("logo") or "",
        "year": item.get("release_year"),
        "releaseInfo": item.get("release_year"),
        "imdb_id": item.get("imdb_id", ""),
        "moviedb_id": item.get("tmdb_id", ""),
        "background": item.get("backdrop") or "",
        "genres": item.get("genres") or [],
        "imdbRating": item.get("rating") or "",
        "description": item.get("description") or "",
        "cast": item.get("cast") or [],
        "runtime": item.get("runtime") or "",
    }


def format_stream_details(file_id: str, filename: str, quality: str, size: str):
    try:
        parsed = PTN.parse(filename)
    except Exception:
        parsed = {}

    details = []
    if parsed.get("codec"):
        details.append(parsed["codec"])
    if parsed.get("audio"):
        details.append(parsed["audio"])
    if parsed.get("bitDepth"):
        details.append(f"{parsed['bitDepth']}bit")
    if parsed.get("encoder"):
        details.append(parsed["encoder"])

    extra = " | ".join(details)

    prefix = "Link" if file_id.startswith(("http://", "https://")) else "Telegram"
    name = f"{prefix} {quality}"
    if extra:
        name += f" ({extra})"

    title = f"📁 {filename}\n💾 {size}"
    return name, title


def get_resolution_priority(name: str) -> int:
    res = {
        "2160p": 2160, "4k": 2160,
        "1080p": 1080,
        "720p": 720,
        "480p": 480,
        "360p": 360
    }
    for k, v in res.items():
        if k in name.lower():
            return v
    return 1

# ---------------- Manifest ----------------
@router.get("/manifest.json")
async def manifest():
    return {
        "id": "telegram.media",
        "version": ADDON_VERSION,
        "name": ADDON_NAME,
        "description": "Dizi ve film arşivim.",
        "logo": "https://i.postimg.cc/XqWnmDXr/Picsart-25-10-09-08-09-45-867.png",
        "types": ["movie", "series"],
        "resources": ["catalog", "meta", "stream"],
        "catalogs": [
            {"type": "movie", "id": "latest_movies", "name": "Latest",
             "extra": [{"name": "genre", "options": GENRES}, {"name": "skip"}]},
            {"type": "movie", "id": "top_movies", "name": "Popular",
             "extra": [{"name": "genre", "options": GENRES}, {"name": "skip"}, {"name": "search"}]},
            {"type": "series", "id": "latest_series", "name": "Latest",
             "extra": [{"name": "genre", "options": GENRES}, {"name": "skip"}]},
            {"type": "series", "id": "top_series", "name": "Popular",
             "extra": [{"name": "genre", "options": GENRES}, {"name": "skip"}, {"name": "search"}]},
        ],
    }

# ---------------- Stream ----------------
@router.get("/stream/{media_type}/{id}.json")
async def get_streams(media_type: str, id: str):
    try:
        parts = id.split(":")
        base_id = parts[0]
        season = int(parts[1]) if len(parts) > 1 else None
        episode = int(parts[2]) if len(parts) > 2 else None
        tmdb_id, db_index = map(int, base_id.split("-"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID")

    media = await db.get_media_details(
        tmdb_id=tmdb_id,
        db_index=db_index,
        season_number=season,
        episode_number=episode
    )

    if not media or "telegram" not in media:
        return {"streams": []}

    streams = []

    for q in media["telegram"]:
        file_id = q.get("id")
        if not file_id:
            continue

        filename = q.get("name", "")
        quality = q.get("quality", "HD")
        size = q.get("size", "")

        name, title = format_stream_details(
            file_id=file_id,
            filename=filename,
            quality=quality,
            size=size
        )

        if file_id.startswith(("http://", "https://")):
            stream_url = file_id
        else:
            stream_url = f"{BASE_URL}/dl/{file_id}/video.mkv"

        streams.append({
            "name": name,
            "title": title,
            "url": stream_url
        })

    streams.sort(key=lambda s: get_resolution_priority(s["name"]), reverse=True)
    return {"streams": streams}
