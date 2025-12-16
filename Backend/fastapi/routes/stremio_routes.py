from fastapi import APIRouter
from typing import Optional
from urllib.parse import unquote
from Backend.config import Telegram
from Backend import db, __version__
import PTN
from datetime import datetime, timezone, timedelta
import re


# ---------------- CONFIG ----------------
BASE_URL = Telegram.BASE_URL
ADDON_NAME = "Arşivim"
ADDON_VERSION = __version__
PAGE_SIZE = 15

router = APIRouter(prefix="/stremio", tags=["Stremio Addon"])


# ---------------- GENRES ----------------
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


# ---------------- HELPERS ----------------
def parse_size_to_mb(size: str) -> float:
    if not size:
        return 0
    m = re.search(r"([\d.,]+)\s*(gb|mb)", size.lower())
    if not m:
        return 0
    value = float(m.group(1).replace(",", "."))
    return value * 1024 if m.group(2) == "gb" else value


def get_source_priority(file_id: str) -> int:
    return 1 if file_id.startswith(("http://", "https://")) else 0


def get_resolution_priority(text: str) -> int:
    mapping = {
        "2160p": 2160, "4k": 2160,
        "1440p": 1440,
        "1080p": 1080,
        "720p": 720,
        "540p": 540,
        "480p": 480,
        "360p": 360,
    }
    text = text.lower()
    for k, v in mapping.items():
        if k in text:
            return v
    return 1


def convert_to_stremio_meta(item: dict) -> dict:
    media_type = "series" if item.get("media_type") == "tv" else "movie"
    return {
        "id": f"{item.get('tmdb_id')}-{item.get('db_index')}",
        "type": media_type,
        "name": item.get("title"),
        "poster": item.get("poster") or "",
        "logo": item.get("logo") or "",
        "year": item.get("release_year"),
        "background": item.get("backdrop") or "",
        "genres": item.get("genres") or [],
        "imdbRating": item.get("rating") or "",
        "description": item.get("description") or "",
    }


def format_stream_details(filename: str, quality: str, size: str, file_id: str):
    source = "Link" if get_source_priority(file_id) else "Telegram"

    try:
        parsed = PTN.parse(filename)
        resolution = parsed.get("resolution", quality)
        quality_type = parsed.get("quality", "")
        codec = parsed.get("codec", "")
    except Exception:
        return f"{source} {quality}", f"📁 {filename}\n💾 {size}"

    name = f"{source} {resolution} {quality_type}".strip()
    title = f"📁 {filename}\n💾 {size}\n🎥 {codec}" if codec else f"📁 {filename}\n💾 {size}"
    return name, title


# ---------------- MANIFEST ----------------
@router.get("/manifest.json")
async def manifest():
    return {
        "id": "telegram.media",
        "version": ADDON_VERSION,
        "name": ADDON_NAME,
        "description": "Dizi ve film arşivim.",
        "types": ["movie", "series"],
        "resources": ["catalog", "meta", "stream"],
        "catalogs": [],
    }


# ---------------- STREAMS ----------------
@router.get("/stream/{media_type}/{id}.json")
async def streams(media_type: str, id: str):
    parts = id.split(":")
    tmdb_id, db_index = map(int, parts[0].split("-"))
    season = int(parts[1]) if len(parts) > 1 else None
    episode = int(parts[2]) if len(parts) > 2 else None

    media = await db.get_media_details(tmdb_id, db_index, season, episode)
    if not media or "telegram" not in media:
        return {"streams": []}

    streams = []

    for q in media["telegram"]:
        file_id = q["id"]
        filename = q.get("name", "")
        quality = q.get("quality", "HD")
        size = q.get("size", "")

        name, title = format_stream_details(filename, quality, size, file_id)

        url = file_id if get_source_priority(file_id) else f"{BASE_URL}/dl/{file_id}/video.mkv"

        streams.append({
            "name": name,
            "title": title,
            "url": url,
            "_source": get_source_priority(file_id),
            "_res": get_resolution_priority(name),
            "_size": parse_size_to_mb(size),
        })

    streams.sort(
        key=lambda s: (s["_source"], s["_res"], s["_size"]),
        reverse=True
    )

    for s in streams:
        s.pop("_source", None)
        s.pop("_res", None)
        s.pop("_size", None)

    return {"streams": streams}
