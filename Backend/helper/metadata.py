import asyncio
import traceback
import PTN
import re
from re import compile, IGNORECASE

from Backend.helper.imdb import get_detail, get_season, search_title
from themoviedb import aioTMDb
from Backend.config import Telegram
import Backend
from Backend.logger import LOGGER
from Backend.helper.encrypt import encode_string

# ----------------- Configuration -----------------
tmdb = aioTMDb(
    key=Telegram.TMDB_API,
    language="en-US",
    region="US"
)

API_SEMAPHORE = asyncio.Semaphore(12)

# ----------------- Simple Caches -----------------
IMDB_CACHE = {}
TMDB_SEARCH_CACHE = {}
TMDB_DETAILS_CACHE = {}
EPISODE_CACHE = {}

# ----------------- TMDb → TR Genre Map -----------------
GENRE_MAP = {
    "Action": "Aksiyon",
    "Adventure": "Macera",
    "Animation": "Animasyon",
    "Comedy": "Komedi",
    "Crime": "Suç",
    "Documentary": "Belgesel",
    "Drama": "Dram",
    "Family": "Aile",
    "Fantasy": "Fantastik",
    "History": "Tarih",
    "Horror": "Korku",
    "Music": "Müzik",
    "Mystery": "Gizem",
    "Romance": "Romantik",
    "Science Fiction": "Bilim Kurgu",
    "TV Movie": "TV Filmi",
    "Thriller": "Gerilim",
    "War": "Savaş",
    "Western": "Vahşi Batı",
    "Action & Adventure": "Aksiyon ve Macera",
    "Kids": "Çocuklar",
    "Reality": "Gerçeklik",
    "Sci-Fi & Fantasy": "Bilim Kurgu ve Fantazi",
    "Soap": "Pembe Dizi",
    "Talk": "Talk-Show",
    "War & Politics": "Savaş ve Politika",
}

# ----------------- Helpers -----------------
def format_tmdb_image(path: str, size="w500") -> str:
    if not path:
        return ""
    return f"https://image.tmdb.org/t/p/{size}{path}"


def get_tmdb_logo(images) -> str:
    if not images:
        return ""
    logos = getattr(images, "logos", None)
    if not logos:
        return ""
    for logo in logos:
        if getattr(logo, "iso_639_1", None) == "en" and getattr(logo, "file_path", None):
            return format_tmdb_image(logo.file_path, "w300")
    for logo in logos:
        if getattr(logo, "file_path", None):
            return format_tmdb_image(logo.file_path, "w300")
    return ""


def format_imdb_images(imdb_id: str) -> dict:
    if not imdb_id:
        return {"poster": "", "backdrop": "", "logo": ""}
    return {
        "poster": f"https://images.metahub.space/poster/small/{imdb_id}/img",
        "backdrop": f"https://images.metahub.space/background/medium/{imdb_id}/img",
        "logo": f"https://images.metahub.space/logo/medium/{imdb_id}/img",
    }


def normalize_genres(tmdb_genres):
    genres = []
    for g in tmdb_genres or []:
        name = getattr(g, "name", None)
        if not name:
            continue
        tr = GENRE_MAP.get(name, name)
        if tr not in genres:
            genres.append(tr)
    return genres


def extract_default_id(text: str):
    if not text:
        return None
    imdb_match = re.search(r'(tt\d+)', text)
    if imdb_match:
        return imdb_match.group(1)
    tmdb_match = re.search(r'/((movie|tv))/(\d+)', text)
    if tmdb_match:
        return tmdb_match.group(3)
    return None


# ----------------- Safe Searches -----------------
async def safe_imdb_search(title: str, type_: str):
    key = f"{type_}:{title}"
    if key in IMDB_CACHE:
        return IMDB_CACHE[key]
    try:
        async with API_SEMAPHORE:
            res = await search_title(query=title, type=type_)
        imdb_id = res["id"] if res else None
        IMDB_CACHE[key] = imdb_id
        return imdb_id
    except Exception:
        return None


async def safe_tmdb_search(title: str, type_: str, year=None):
    key = f"{type_}:{title}:{year}"
    if key in TMDB_SEARCH_CACHE:
        return TMDB_SEARCH_CACHE[key]
    try:
        async with API_SEMAPHORE:
            if type_ == "movie":
                res = await tmdb.search().movies(query=title, year=year)
            else:
                res = await tmdb.search().tv(query=title)
        item = res[0] if res else None
        TMDB_SEARCH_CACHE[key] = item
        return item
    except Exception:
        TMDB_SEARCH_CACHE[key] = None
        return None


# ----------------- TMDb Details -----------------
async def tmdb_movie_details(movie_id):
    if movie_id in TMDB_DETAILS_CACHE:
        return TMDB_DETAILS_CACHE[movie_id]
    try:
        async with API_SEMAPHORE:
            details = await tmdb.movie(movie_id).details(
                append_to_response="external_ids,credits,images"
            )
        TMDB_DETAILS_CACHE[movie_id] = details
        return details
    except Exception:
        TMDB_DETAILS_CACHE[movie_id] = None
        return None


async def tmdb_tv_details(tv_id):
    if tv_id in TMDB_DETAILS_CACHE:
        return TMDB_DETAILS_CACHE[tv_id]
    try:
        async with API_SEMAPHORE:
            details = await tmdb.tv(tv_id).details(
                append_to_response="external_ids,credits,images"
            )
        TMDB_DETAILS_CACHE[tv_id] = details
        return details
    except Exception:
        TMDB_DETAILS_CACHE[tv_id] = None
        return None


async def tmdb_episode_details(tv_id, season, episode):
    key = f"{tv_id}:{season}:{episode}"
    if key in EPISODE_CACHE:
        return EPISODE_CACHE[key]
    try:
        async with API_SEMAPHORE:
            ep = await tmdb.episode(tv_id, season, episode).details()
        EPISODE_CACHE[key] = ep
        return ep
    except Exception:
        EPISODE_CACHE[key] = None
        return None


# ----------------- MAIN METADATA -----------------
async def metadata(filename: str, channel: int, msg_id):
    try:
        parsed = PTN.parse(filename)
    except Exception as e:
        LOGGER.error(f"PTN parse error: {e}")
        return None

    # Skip multipart
    if compile(r'(?:part|cd|disc)[s._-]*\d+', IGNORECASE).search(filename):
        return None

    title = parsed.get("title")
    season = parsed.get("season")
    episode = parsed.get("episode")
    year = parsed.get("year")
    quality = parsed.get("resolution")

    if not title or not quality:
        return None

    data = {"chat_id": channel, "msg_id": msg_id}
    try:
        encoded_string = await encode_string(data)
    except Exception:
        encoded_string = None

    try:
        if season and episode:
            return await fetch_tv_metadata(
                title, season, episode, encoded_string, year, quality
            )
        else:
            return await fetch_movie_metadata(
                title, encoded_string, year, quality
            )
    except Exception as e:
        LOGGER.error(f"Metadata error: {e}\n{traceback.format_exc()}")
        return None


# ----------------- MOVIE -----------------
async def fetch_movie_metadata(title, encoded_string, year, quality):
    imdb_id = await safe_imdb_search(title, "movie")
    imdb_data = None

    if imdb_id:
        try:
            imdb_data = await get_detail(imdb_id, "movie")
        except Exception:
            imdb_data = None

    if imdb_data:
        images = format_imdb_images(imdb_id)
        return {
            "tmdb_id": imdb_data.get("moviedb_id") or imdb_id.replace("tt", ""),
            "imdb_id": imdb_id,
            "title": imdb_data.get("title", title),
            "year": imdb_data.get("releaseDetailed", {}).get("year", 0),
            "rate": imdb_data.get("rating", {}).get("star", 0),
            "description": imdb_data.get("plot", ""),
            "poster": images["poster"],
            "backdrop": images["backdrop"],
            "logo": images["logo"],
            "cast": imdb_data.get("cast", []),
            "runtime": str(imdb_data.get("runtime") or ""),
            "genres": imdb_data.get("genre", []),
            "media_type": "movie",
            "quality": quality,
            "encoded_string": encoded_string,
        }

    tmdb_item = await safe_tmdb_search(title, "movie", year)
    if not tmdb_item:
        return None

    movie = await tmdb_movie_details(tmdb_item.id)
    if not movie:
        return None

    return {
        "tmdb_id": movie.id,
        "imdb_id": getattr(movie.external_ids, "imdb_id", None),
        "title": movie.title,
        "year": movie.release_date.year if movie.release_date else 0,
        "rate": movie.vote_average or 0,
        "description": movie.overview or "",
        "poster": format_tmdb_image(movie.poster_path),
        "backdrop": format_tmdb_image(movie.backdrop_path, "original"),
        "logo": get_tmdb_logo(getattr(movie, "images", None)),
        "cast": [c.name for c in (movie.credits.cast or [])],
        "runtime": f"{movie.runtime} min" if movie.runtime else "",
        "genres": normalize_genres(movie.genres),
        "media_type": "movie",
        "quality": quality,
        "encoded_string": encoded_string,
    }


# ----------------- TV -----------------
async def fetch_tv_metadata(title, season, episode, encoded_string, year, quality):
    imdb_id = await safe_imdb_search(title, "tvSeries")
    imdb_tv = None
    imdb_ep = None

    if imdb_id:
        try:
            imdb_tv = await get_detail(imdb_id, "tvSeries")
            imdb_ep = await get_season(imdb_id, season, episode)
        except Exception:
            imdb_tv = None

    if imdb_tv:
        images = format_imdb_images(imdb_id)
        return {
            "tmdb_id": imdb_tv.get("moviedb_id") or imdb_id.replace("tt", ""),
            "imdb_id": imdb_id,
            "title": imdb_tv.get("title", title),
            "year": imdb_tv.get("releaseDetailed", {}).get("year", 0),
            "rate": imdb_tv.get("rating", {}).get("star", 0),
            "description": imdb_tv.get("plot", ""),
            "poster": images["poster"],
            "backdrop": images["backdrop"],
            "logo": images["logo"],
            "cast": imdb_tv.get("cast", []),
            "runtime": str(imdb_tv.get("runtime") or ""),
            "genres": imdb_tv.get("genre", []),
            "media_type": "tv",
            "season_number": season,
            "episode_number": episode,
            "episode_title": imdb_ep.get("title", f"S{season}E{episode}") if imdb_ep else "",
            "episode_overview": imdb_ep.get("plot", "") if imdb_ep else "",
            "quality": quality,
            "encoded_string": encoded_string,
        }

    tmdb_item = await safe_tmdb_search(title, "tv", year)
    if not tmdb_item:
        return None

    tv = await tmdb_tv_details(tmdb_item.id)
    if not tv:
        return None

    ep = await tmdb_episode_details(tv.id, season, episode)

    return {
        "tmdb_id": tv.id,
        "imdb_id": getattr(tv.external_ids, "imdb_id", None),
        "title": tv.name,
        "year": tv.first_air_date.year if tv.first_air_date else 0,
        "rate": tv.vote_average or 0,
        "description": tv.overview or "",
        "poster": format_tmdb_image(tv.poster_path),
        "backdrop": format_tmdb_image(tv.backdrop_path, "original"),
        "logo": get_tmdb_logo(getattr(tv, "images", None)),
        "cast": [c.name for c in (tv.credits.cast or [])],
        "runtime": "",
        "genres": normalize_genres(tv.genres),
        "media_type": "tv",
        "season_number": season,
        "episode_number": episode,
        "episode_title": ep.name if ep else f"S{season}E{episode}",
        "episode_overview": ep.overview if ep else "",
        "quality": quality,
        "encoded_string": encoded_string,
    }
