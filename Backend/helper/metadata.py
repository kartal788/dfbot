import asyncio
import re
import traceback
import PTN
from Backend.helper.imdb import get_detail, get_season, search_title
from themoviedb import aioTMDb
from Backend.config import Telegram
import Backend
from Backend.logger import LOGGER
from Backend.helper.encrypt import encode_string

# ----------------- Configuration -----------------
DELAY = 0
tmdb = aioTMDb(key=Telegram.TMDB_API, language="en-US", region="US")

# ----------------- SIMPLE CACHES (NO DEPENDENCY) -----------------
IMDB_CACHE = {}
TMDB_SEARCH_CACHE = {}
TMDB_DETAILS_CACHE = {}
EPISODE_CACHE = {}

API_SEMAPHORE = asyncio.Semaphore(12)

# ----------------- GENRE MAP (TMDB → TR) -----------------
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

PLATFORM_MAP = {
    "nf": "Netflix",
    "netflix": "Netflix",
    "dsnp": "Disney",
    "disney": "Disney",
    "hbomax": "Max",
    "hbo": "Max",
    "max": "Max",
    "amzn": "Amazon",
    "amazon": "Amazon",
    "exxen": "Exxen",
    "gain": "Gain",
    "tabii": "Tabii",
    "tod": "Tod",
}

# ----------------- HELPERS -----------------
def normalize_genres(tmdb_genres, telegram_names):
    genres = []
    for g in tmdb_genres or []:
        name = g.name if hasattr(g, "name") else str(g)
        tr = GENRE_MAP.get(name, name)
        if tr not in genres:
            genres.append(tr)

    for t in telegram_names or []:
        low = t.lower()
        for key, val in PLATFORM_MAP.items():
            if key in low and val not in genres:
                genres.append(val)

    return genres


def format_tmdb_image(path: str, size="w500"):
    return f"https://image.tmdb.org/t/p/{size}{path}" if path else ""


# ----------------- MAIN METADATA -----------------
async def metadata(filename: str, channel: int, msg_id):
    try:
        parsed = PTN.parse(filename)
    except Exception:
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
    except:
        encoded_string = None

    if season and episode:
        return await fetch_tv_metadata(title, season, episode, encoded_string, year, quality)
    else:
        return await fetch_movie_metadata(title, encoded_string, year, quality)


# ----------------- MOVIE -----------------
async def fetch_movie_metadata(title, encoded_string, year, quality):
    imdb_id = await search_title(title, "movie")
    movie = None

    if imdb_id:
        movie = await get_detail(imdb_id, "movie")

    if not movie:
        res = await tmdb.search().movies(query=title, year=year)
        if not res:
            return None
        movie = await tmdb.movie(res[0].id).details(append_to_response="credits,images")

    genres = normalize_genres(movie.genres, [])

    return {
        "title": movie.title,
        "year": year,
        "imdb_id": getattr(movie.external_ids, "imdb_id", None),
        "tmdb_id": movie.id,
        "rate": movie.vote_average,
        "description": movie.overview,
        "poster": format_tmdb_image(movie.poster_path),
        "backdrop": format_tmdb_image(movie.backdrop_path, "original"),
        "genres": genres,
        "media_type": "movie",
        "quality": quality,
        "encoded_string": encoded_string,
    }


# ----------------- TV -----------------
async def fetch_tv_metadata(title, season, episode, encoded_string, year, quality):
    res = await tmdb.search().tv(query=title)
    if not res:
        return None

    tv = await tmdb.tv(res[0].id).details(append_to_response="credits,images")
    ep = await tmdb.episode(tv.id, season, episode).details()

    genres = normalize_genres(tv.genres, [])

    return {
        "title": tv.name,
        "year": year,
        "imdb_id": getattr(tv.external_ids, "imdb_id", None),
        "tmdb_id": tv.id,
        "rate": tv.vote_average,
        "description": tv.overview,
        "poster": format_tmdb_image(tv.poster_path),
        "backdrop": format_tmdb_image(tv.backdrop_path, "original"),
        "genres": genres,
        "media_type": "tv",
        "season_number": season,
        "episode_number": episode,
        "episode_title": ep.name if ep else "",
        "episode_overview": ep.overview if ep else "",
        "quality": quality,
        "encoded_string": encoded_string,
    }
