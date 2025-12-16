from fastapi import APIRouter, HTTPException
from typing import Optional
from urllib.parse import unquote
from Backend.config import Telegram
from Backend import db, __version__
import PTN
from datetime import datetime, timezone, timedelta

BASE_URL = Telegram.BASE_URL
ADDON_NAME = "Arşivim"
ADDON_VERSION = __version__
PAGE_SIZE = 15

router = APIRouter(prefix="/stremio", tags=["Stremio Addon"])

# ---------- HELPERS ----------

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


def format_stream_details(filename: str, quality: str, size: str):
    try:
        parsed = PTN.parse(filename)
    except Exception:
        return (quality, f"📁 {filename}\n💾 {size}")

    resolution = parsed.get("resolution", quality)
    stream_name = resolution

    title = f"📁 {filename}\n💾 {size}"
    return stream_name, title


def get_resolution_priority(name: str) -> int:
    table = {
        "2160p": 2160, "4k": 2160,
        "1080p": 1080,
        "720p": 720,
        "480p": 480
    }
    name = name.lower()
    for k, v in table.items():
        if k in name:
            return v
    return 1


def parse_size(size: str) -> int:
    if not size:
        return 0
    try:
        s = size.lower().replace(" ", "")
        if "gb" in s:
            return int(float(s.replace("gb", "")) * 1024)
        if "mb" in s:
            return int(float(s.replace("mb", "")))
    except:
        pass
    return 0


def is_http(url: str) -> int:
    return 1 if url.startswith("http") else 0


# ---------- CATALOG ----------

@router.get("/catalog/{media_type}/{id}/{extra:path}.json")
@router.get("/catalog/{media_type}/{id}.json")
async def get_catalog(media_type: str, id: str, extra: Optional[str] = None):

    genre_filter = None
    search_query = None
    stremio_skip = 0

    if extra:
        params = extra.split("&")   # 🔥 FIX
        for p in params:
            if p.startswith("genre="):
                genre_filter = unquote(p.replace("genre=", ""))
            elif p.startswith("search="):
                search_query = unquote(p.replace("search=", ""))
            elif p.startswith("skip="):
                stremio_skip = int(p.replace("skip=", "0"))

    page = (stremio_skip // PAGE_SIZE) + 1

    if search_query:
        result = await db.search_documents(search_query, page, PAGE_SIZE)
        items = result.get("results", [])
        items = [i for i in items if i["media_type"] == ("tv" if media_type == "series" else "movie")]
    else:
        sort = [("updated_on", "desc")]
        if media_type == "movie":
            data = await db.sort_movies(sort, page, PAGE_SIZE, genre_filter)
            items = data.get("movies", [])
        else:
            data = await db.sort_tv_shows(sort, page, PAGE_SIZE, genre_filter)
            items = data.get("tv_shows", [])

    return {"metas": [convert_to_stremio_meta(i) for i in items]}


# ---------- STREAM ----------

@router.get("/stream/{media_type}/{id}.json")
async def get_streams(media_type: str, id: str):

    parts = id.split(":")
    tmdb_id, db_index = map(int, parts[0].split("-"))
    season = int(parts[1]) if len(parts) > 1 else None
    episode = int(parts[2]) if len(parts) > 2 else None

    media = await db.get_media_details(tmdb_id, db_index, season, episode)
    if not media or "telegram" not in media:
        return {"streams": []}

    streams = []

    for q in media["telegram"]:
        name, title = format_stream_details(
            q.get("name", ""),
            q.get("quality", ""),
            q.get("size", "")
        )

        url = f"{BASE_URL}/dl/{q['id']}/video.mkv"

        streams.append({
            "name": name,
            "title": title,
            "url": url,
            "_res": get_resolution_priority(name),
            "_http": is_http(url),
            "_size": parse_size(q.get("size", ""))
        })

    # 🔥 FINAL SORT
    streams.sort(
        key=lambda s: (s["_res"], s["_http"], s["_size"]),
        reverse=True
    )

    for s in streams:
        s.pop("_res")
        s.pop("_http")
        s.pop("_size")

    return {"streams": streams}
