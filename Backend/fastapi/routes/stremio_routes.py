from fastapi import APIRouter
from typing import Optional
from urllib.parse import unquote
from datetime import datetime, timezone, timedelta

import PTN

from Backend.config import Telegram
from Backend import db, __version__


# ─── CONFIG ────────────────────────────────────────────────────────────────────
BASE_URL = Telegram.BASE_URL
ADDON_NAME = "Arşivim"
ADDON_VERSION = __version__
PAGE_SIZE = 15

router = APIRouter(prefix="/stremio", tags=["Stremio Addon"])


# ─── GENRES ─────────────────────────────────────────────────────────────────────
GENRES = [
    "Aile", "Aksiyon", "Animasyon", "Belgesel", "Bilim Kurgu",
    "Çocuklar", "Dram", "Fantastik", "Gerilim", "Gizem",
    "Komedi", "Korku", "Macera", "Romantik", "Savaş", "Suç"
]


# ─── PLATFORMS ──────────────────────────────────────────────────────────────────
PLATFORMS = {
    "netflix": ["nf"],
    "amazon": ["amzn"],
    "disney": ["dsnp"],
    "hbo": ["hbo", "hbomax", "blutv"],
}


# ─── HELPERS ────────────────────────────────────────────────────────────────────
def detect_platform_from_name(name: str) -> Optional[str]:
    if not name:
        return None

    search_space = name.lower()

    try:
        parsed = PTN.parse(name)
        for v in parsed.values():
            if isinstance(v, str):
                search_space += " " + v.lower()
    except Exception:
        pass

    for platform, keys in PLATFORMS.items():
        for k in keys:
            if k in search_space:
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
        "background": item.get("backdrop") or "",
        "year": item.get("release_year"),
        "genres": item.get("genres") or [],
        "description": item.get("description") or "",
        "imdbRating": item.get("rating") or "",
    }


def build_platform_catalogs():
    catalogs = []

    for platform in PLATFORMS.keys():
        catalogs.append({
            "type": "movie",
            "id": f"{platform}_movies",
            "name": f"{platform.capitalize()} Filmleri",
            "extra": [{"name": "genre", "options": GENRES}, {"name": "skip"}],
            "extraSupported": ["genre", "skip"]
        })

        catalogs.append({
            "type": "series",
            "id": f"{platform}_series",
            "name": f"{platform.capitalize()} Dizileri",
            "extra": [{"name": "genre", "options": GENRES}, {"name": "skip"}],
            "extraSupported": ["genre", "skip"]
        })

    return catalogs


# ─── MANIFEST ───────────────────────────────────────────────────────────────────
@router.get("/manifest.json")
async def manifest():
    base_catalogs = [
        {
            "type": "movie",
            "id": "latest_movies",
            "name": "Latest Filmler",
            "extra": [{"name": "genre", "options": GENRES}, {"name": "skip"}],
            "extraSupported": ["genre", "skip"]
        },
        {
            "type": "series",
            "id": "latest_series",
            "name": "Latest Diziler",
            "extra": [{"name": "genre", "options": GENRES}, {"name": "skip"}],
            "extraSupported": ["genre", "skip"]
        },
    ]

    return {
        "id": "telegram.media",
        "version": ADDON_VERSION,
        "name": ADDON_NAME,
        "description": "Platform bazlı dizi ve film arşivi",
        "types": ["movie", "series"],
        "resources": ["catalog", "meta", "stream"],
        "catalogs": base_catalogs + build_platform_catalogs(),
    }


# ─── CATALOG ────────────────────────────────────────────────────────────────────
@router.get("/catalog/{media_type}/{id}/{extra:path}.json")
@router.get("/catalog/{media_type}/{id}.json")
async def catalog(media_type: str, id: str, extra: Optional[str] = None):
    skip = 0
    genre = None
    platform = None

    if extra:
        for p in extra.replace("&", "/").split("/"):
            if p.startswith("genre="):
                genre = unquote(p[6:])
            elif p.startswith("skip="):
                skip = int(p[5:] or 0)

    page = (skip // PAGE_SIZE) + 1

    for p in PLATFORMS.keys():
        if id.startswith(p):
            platform = p
            break

    if media_type == "movie":
        data = await db.sort_movies(
            sort=[("updated_on", "desc")],
            page=page,
            page_size=PAGE_SIZE,
            genre=genre,
            platform=platform
        )
        items = data.get("movies", [])
    else:
        data = await db.sort_tv_shows(
            sort=[("updated_on", "desc")],
            page=page,
            page_size=PAGE_SIZE,
            genre=genre,
            platform=platform
        )
        items = data.get("tv_shows", [])

    # fallback: platform db’de yoksa name ile ayıkla
    if platform:
        items = [
            i for i in items
            if detect_platform_from_name(i.get("name", "")) == platform
        ]

    return {"metas": [convert_to_stremio_meta(i) for i in items]}


# ─── META ───────────────────────────────────────────────────────────────────────
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
                })

        meta_obj["videos"] = videos

    return {"meta": meta_obj}


# ─── STREAM ─────────────────────────────────────────────────────────────────────
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
        name = q.get("name", "")

        url = (
            file_id if file_id.startswith("http")
            else f"{BASE_URL}/dl/{file_id}/video.mkv"
        )

        streams.append({
            "name": name,
            "title": name,
            "url": url
        })

    return {"streams": streams}
