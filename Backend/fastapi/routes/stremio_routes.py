from fastapi import APIRouter
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

# --- Genres ---
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

# --- Helpers ---
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
        "imdbRating": item.get("rating") or ""
    }

# --- Manifest ---
@router.get("/manifest.json")
async def manifest():
    return {
        "id": "telegram.media",
        "version": ADDON_VERSION,
        "name": ADDON_NAME,
        "description": "Dizi ve film arşivim.",
        "types": ["movie", "series"],
        "resources": ["catalog", "meta", "stream"],
        "catalogs": [
            {
                "type": "movie",
                "id": "movies",
                "name": "Filmler",
                "genres": GENRES,
                "extra": [
                    {"name": "genre"},
                    {"name": "search"},
                    {"name": "skip"}
                ]
            },
            {
                "type": "series",
                "id": "series",
                "name": "Diziler",
                "genres": GENRES,
                "extra": [
                    {"name": "genre"},
                    {"name": "search"},
                    {"name": "skip"}
                ]
            }
        ]
    }

# --- Catalog ---
@router.get("/catalog/{media_type}/{catalog_id}/{extra:path}.json")
@router.get("/catalog/{media_type}/{catalog_id}.json")
async def catalog(media_type: str, catalog_id: str, extra: Optional[str] = None):
    skip = 0
    genre = None
    search = None

    if extra:
        for part in extra.split("/"):
            if part.startswith("genre="):
                genre = unquote(part.replace("genre=", ""))
            elif part.startswith("search="):
                search = unquote(part.replace("search=", ""))
            elif part.startswith("skip="):
                skip = int(part.replace("skip=", "0"))

    page = (skip // PAGE_SIZE) + 1

    if search:
        data = await db.search_documents(search, page, PAGE_SIZE)
        items = data.get("results", [])
    else:
        if media_type == "movie":
            data = await db.sort_movies([("updated_on", "desc")], page, PAGE_SIZE, genre)
            items = data.get("movies", [])
        else:
            data = await db.sort_tv_shows([("updated_on", "desc")], page, PAGE_SIZE, genre)
            items = data.get("tv_shows", [])

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
                    "released": e.get("released") or yesterday
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
        url = file_id if file_id.startswith("http") else f"{BASE_URL}/dl/{file_id}/video.mkv"
        streams.append({
            "name": q.get("quality", "HD"),
            "title": q.get("name", ""),
            "url": url
        })

    return {"streams": streams}
