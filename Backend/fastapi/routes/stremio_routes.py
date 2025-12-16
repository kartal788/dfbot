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


# --- Genres ---
GENRES = [
    "Aile", "Aksiyon", "Animasyon", "Belgesel", "Bilim Kurgu",
    "Biyografi", "Çocuklar", "Dram", "Fantastik", "Gerilim",
    "Gizem", "Komedi", "Korku", "Macera", "Romantik", "Suç",
    "Tarih", "Savaş"
]


# --- Platform Map ---
PLATFORM_KEYWORDS = {
    "nf": "Netflix",
    "netflix": "Netflix",
    "dsnp": "Disney",
    "disney": "Disney",
    "amzn": "Amazon",
    "amazon": "Amazon",
    "blutv": "HBO",
    "hbo": "HBO",
    "hbomax": "HBO",
}


# --- Helpers ---
def detect_platform_from_name(name: str) -> Optional[str]:
    try:
        parsed = PTN.parse(name)
    except Exception:
        return None

    text = name.lower()
    for k, v in PLATFORM_KEYWORDS.items():
        if k in text:
            return v
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


def format_stream_details(filename: str, quality: str, size: str, file_id: str):
    try:
        parsed = PTN.parse(filename)
    except Exception:
        return f"{quality}", f"{filename}\n{size}"

    platform = detect_platform_from_name(filename)
    platform_tag = f"[{platform}]" if platform else ""

    resolution = parsed.get("resolution", quality)
    codec = parsed.get("codec", "")
    audio = parsed.get("audio", "")

    name = f"{platform_tag} {resolution}".strip()
    title = "\n".join(filter(None, [
        f"📁 {filename}",
        f"💾 {size}",
        codec,
        audio
    ]))

    return name, title


def parse_size(size_str: str) -> float:
    if not size_str:
        return 0.0
    size_str = size_str.lower().replace(" ", "")
    try:
        if "gb" in size_str:
            return float(size_str.replace("gb", "")) * 1024
        if "mb" in size_str:
            return float(size_str.replace("mb", ""))
    except ValueError:
        pass
    return 0.0


# --- Manifest ---
@router.get("/manifest.json")
async def manifest():
    catalogs = []

    for platform in ["Netflix", "Amazon", "Disney", "HBO"]:
        catalogs.extend([
            {
                "type": "movie",
                "id": f"{platform.lower()}_movies",
                "name": f"{platform} Filmleri",
                "extraSupported": ["sort", "skip"],
                "extra": [{"name": "sort", "options": ["updated_on", "rating", "released"]}]
            },
            {
                "type": "series",
                "id": f"{platform.lower()}_series",
                "name": f"{platform} Dizileri",
                "extraSupported": ["sort", "skip"],
                "extra": [{"name": "sort", "options": ["updated_on", "rating", "released"]}]
            }
        ])

    return {
        "id": "telegram.media",
        "version": ADDON_VERSION,
        "name": ADDON_NAME,
        "description": "Dizi ve film arşivim",
        "types": ["movie", "series"],
        "resources": ["catalog", "meta", "stream"],
        "catalogs": catalogs
    }


# --- Catalog ---
@router.get("/catalog/{media_type}/{id}/{extra:path}.json")
@router.get("/catalog/{media_type}/{id}.json")
async def catalog(media_type: str, id: str, extra: Optional[str] = None):
    skip = 0
    sort_key = "updated_on"

    if extra:
        for p in extra.replace("&", "/").split("/"):
            if p.startswith("skip="):
                skip = int(p.replace("skip=", ""))
            elif p.startswith("sort="):
                sort_key = p.replace("sort=", "")

    page = (skip // PAGE_SIZE) + 1

    platform = None
    for p in ["netflix", "amazon", "disney", "hbo"]:
        if id.startswith(p):
            platform = p.capitalize()

    sort = [(sort_key, "desc")]

    if media_type == "movie":
        data = await db.sort_movies(sort, page, PAGE_SIZE, None)
        items = data.get("movies", [])
    else:
        data = await db.sort_tv_shows(sort, page, PAGE_SIZE, None)
        items = data.get("tv_shows", [])

    if platform:
        items = [
            i for i in items
            if any(platform.lower() in (g.lower()) for g in i.get("genres", []))
        ]

    return {"metas": [convert_to_stremio_meta(i) for i in items]}


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

        name, title = format_stream_details(filename, quality, size, file_id)

        url = file_id if file_id.startswith("http") else f"{BASE_URL}/dl/{file_id}/video.mkv"

        streams.append({
            "name": name,
            "title": title,
            "url": url,
            "_size": parse_size(size)
        })

    streams.sort(key=lambda s: s["_size"], reverse=True)
    for s in streams:
        s.pop("_size", None)

    return {"streams": streams}
