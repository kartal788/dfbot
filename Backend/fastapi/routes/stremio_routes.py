from fastapi import APIRouter, HTTPException
from typing import Optional
from urllib.parse import unquote
from Backend.config import Telegram
from Backend import db, __version__
import PTN
from datetime import datetime, timezone, timedelta

# --- Configuration ---
BASE_URL = Telegram.BASE_URL
ADDON_NAME = "Arşivim"
ADDON_VERSION = __version__
PAGE_SIZE = 15

router = APIRouter(prefix="/stremio", tags=["Stremio Addon"])

# --- Platforms ---
PLATFORMS = {
    "netflix": ["nf"],
    "disney": ["dsnp", "disney"],
    "amazon": ["amzn"],
    "hbo": ["hbo", "hbomax", "blutv"]
}

# --- Genres ---
GENRES = [
    "Aile", "Aksiyon", "Animasyon", "Belgesel",
    "Bilim Kurgu", "Biyografi", "Çocuklar",
    "Dram", "Fantastik", "Gerilim", "Gizem",
    "Komedi", "Korku", "Macera", "Romantik",
    "Savaş", "Spor", "Suç", "Tarih"
]

# --- Helpers ---
def detect_platform_from_name(name: str) -> Optional[str]:
    if not name:
        return None
    lname = name.lower()
    for platform, keys in PLATFORMS.items():
        if any(k in lname for k in keys):
            return platform
    return None


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


def get_sort_from_category(cat: str):
    if cat == "rating":
        return [("rating", "desc")]
    if cat == "released":
        return [("release_year", "desc")]
    return [("updated_on", "desc")]


# --- Manifest ---
@router.get("/manifest.json")
async def manifest():
    catalogs = []

    for platform in PLATFORMS.keys():
        for media_type in ["movie", "series"]:
            for cat in ["updated", "rating", "released"]:
                catalogs.append({
                    "type": media_type,
                    "id": f"{platform}_{media_type}_{cat}",
                    "name": f"{platform.capitalize()} {'Filmleri' if media_type=='movie' else 'Dizileri'} ({cat})",
                    "extra": [{"name": "skip"}],
                    "extraSupported": ["skip"]
                })

    return {
        "id": "telegram.media",
        "version": ADDON_VERSION,
        "name": ADDON_NAME,
        "description": "Platform bazlı film ve dizi arşivi",
        "types": ["movie", "series"],
        "resources": ["catalog", "meta", "stream"],
        "catalogs": catalogs
    }


# --- Catalog ---
@router.get("/catalog/{media_type}/{id}/{extra:path}.json")
@router.get("/catalog/{media_type}/{id}.json")
async def catalog(media_type: str, id: str, extra: Optional[str] = None):
    stremio_skip = 0

    if extra:
        for p in extra.replace("&", "/").split("/"):
            if p.startswith("skip="):
                stremio_skip = int(p[5:] or 0)

    page = (stremio_skip // PAGE_SIZE) + 1

    try:
        platform, _, category = id.split("_", 2)
    except ValueError:
        return {"metas": []}

    sort = get_sort_from_category(category)

    if media_type == "movie":
        data = await db.sort_movies(sort, page, PAGE_SIZE)
        items = data.get("movies", [])
    else:
        data = await db.sort_tv_shows(sort, page, PAGE_SIZE)
        items = data.get("tv_shows", [])

    filtered = []
    for item in items:
        for t in item.get("telegram", []):
            if detect_platform_from_name(t.get("name", "")) == platform:
                filtered.append(item)
                break

    return {"metas": [convert_to_stremio_meta(i) for i in filtered]}


# --- Meta ---
@router.get("/meta/{media_type}/{id}.json")
async def meta(media_type: str, id: str):
    tmdb_id, db_index = map(int, id.split("-"))
    media = await db.get_media_details(tmdb_id, db_index)

    if not media:
        return {"meta": {}}

    meta_obj = convert_to_stremio_meta(media)

    if media_type == "series":
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        videos = []

        for s in media.get("seasons", []):
            for e in s.get("episodes", []):
                videos.append({
                    "id": f"{id}:{s['season_number']}:{e['episode_number']}",
                    "title": e.get("title"),
                    "season": s["season_number"],
                    "episode": e["episode_number"],
                    "released": e.get("released") or yesterday,
                    "overview": e.get("overview"),
                })

        meta_obj["videos"] = videos

    return {"meta": meta_obj}


# --- Streams ---
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

        platform = detect_platform_from_name(filename)
        source = platform.capitalize() if platform else "Kaynak"

        url = (
            file_id
            if file_id.startswith(("http://", "https://"))
            else f"{BASE_URL}/dl/{file_id}/video.mkv"
        )

        streams.append({
            "name": f"{source} {quality}",
            "title": f"📁 {filename}\n💾 {size}",
            "url": url
        })

    return {"streams": streams}
