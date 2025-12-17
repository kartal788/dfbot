import asyncio
import PTN
import re

from Backend.helper.imdb import get_detail, get_season, search_title
from themoviedb import aioTMDb
from Backend.config import Telegram
from Backend.logger import LOGGER
from Backend.helper.encrypt import encode_string

from deep_translator import GoogleTranslator

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
tmdb = aioTMDb(key=Telegram.TMDB_API, language="en-US", region="US")
API_SEMAPHORE = asyncio.Semaphore(12)

TRANSLATOR = GoogleTranslator(source="en", target="tr")
TRANSLATE_CACHE = {}

# -------------------------------------------------
# TRANSLATE (cevir ile aynı mantık)
# -------------------------------------------------
def tr(text: str) -> str:
    if not text or not str(text).strip():
        return ""
    if text in TRANSLATE_CACHE:
        return TRANSLATE_CACHE[text]
    try:
        translated = TRANSLATOR.translate(text)
    except Exception:
        translated = text
    TRANSLATE_CACHE[text] = translated
    return translated

# -------------------------------------------------
# GENRE NORMALIZATION
# -------------------------------------------------
GENRE_TUR_ALIASES = {
    "action": "Aksiyon",
    "adventure": "Macera",
    "animation": "Animasyon",
    "biography": "Biyografi",
    "comedy": "Komedi",
    "crime": "Suç",
    "documentary": "Belgesel",
    "drama": "Dram",
    "family": "Aile",
    "fantasy": "Fantastik",
    "history": "Tarih",
    "horror": "Korku",
    "music": "Müzik",
    "mystery": "Gizem",
    "romance": "Romantik",
    "science fiction": "Bilim Kurgu",
    "thriller": "Gerilim",
    "war": "Savaş",
    "western": "Vahşi Batı",
}

def tur_genre_normalize(genres):
    out = []
    for g in genres or []:
        key = g.lower().strip()
        out.append(GENRE_TUR_ALIASES.get(key, g))
    return out

# -------------------------------------------------
# HELPERS
# -------------------------------------------------
def format_tmdb_image(path, size="w500"):
    return f"https://image.tmdb.org/t/p/{size}{path}" if path else ""

def get_tmdb_logo(images):
    if not images or not getattr(images, "logos", None):
        return ""
    for l in images.logos:
        if l.iso_639_1 == "en" and l.file_path:
            return format_tmdb_image(l.file_path, "w300")
    return ""

def extract_default_id(text):
    if not text:
        return None
    imdb = re.search(r"(tt\d+)", str(text))
    if imdb:
        return imdb.group(1)
    tmdb = re.search(r"/(movie|tv)/(\d+)", str(text))
    if tmdb:
        return tmdb.group(2)
    return None

# -------------------------------------------------
# SAFE SEARCH
# -------------------------------------------------
async def safe_imdb_search(title, type_):
    try:
        async with API_SEMAPHORE:
            res = await search_title(title, type_)
        return res["id"] if res else None
    except Exception:
        return None

async def safe_tmdb_search(title, type_, year=None):
    try:
        async with API_SEMAPHORE:
            res = (
                await tmdb.search().movies(title, year=year)
                if type_ == "movie"
                else await tmdb.search().tv(title)
            )
        return res[0] if res else None
    except Exception:
        return None

# -------------------------------------------------
# MAIN ENTRY
# -------------------------------------------------
async def metadata(filename, channel, msg_id):
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
    if season and not episode:
        return None

    encoded = await encode_string({"chat_id": channel, "msg_id": msg_id})

    default_id = extract_default_id(filename)

    if season:
        return await fetch_tv_metadata(title, season, episode, encoded, year, quality, default_id)

    return await fetch_movie_metadata(title, encoded, year, quality, default_id)

# -------------------------------------------------
# TV METADATA (TR)
# -------------------------------------------------
async def fetch_tv_metadata(title, season, episode, encoded, year, quality, default_id):
    tmdb_id = int(default_id) if default_id and default_id.isdigit() else None

    if not tmdb_id:
        res = await safe_tmdb_search(title, "tv", year)
        if not res:
            return None
        tmdb_id = res.id

    async with API_SEMAPHORE:
        tv = await tmdb.tv(tmdb_id).details(append_to_response="external_ids,credits,images")
        ep = await tmdb.episode(tmdb_id, season, episode).details()

    return {
        "tmdb_id": tv.id,
        "imdb_id": getattr(tv.external_ids, "imdb_id", None),
        "title": tv.name,
        "year": tv.first_air_date.year if tv.first_air_date else 0,
        "rate": tv.vote_average or 0,
        "description": tr(tv.overview),
        "poster": format_tmdb_image(tv.poster_path),
        "backdrop": format_tmdb_image(tv.backdrop_path, "original"),
        "logo": get_tmdb_logo(tv.images),
        "genres": tur_genre_normalize([g.name for g in tv.genres]),
        "cast": [c.name for c in tv.credits.cast],
        "runtime": "",
        "media_type": "tv",
        "season_number": season,
        "episode_number": episode,
        "episode_title": tr(ep.name),
        "episode_backdrop": format_tmdb_image(ep.still_path, "original"),
        "episode_overview": tr(ep.overview),
        "episode_released": ep.air_date.isoformat() if ep.air_date else "",
        "quality": quality,
        "encoded_string": encoded,
    }

# -------------------------------------------------
# MOVIE METADATA (TR)
# -------------------------------------------------
async def fetch_movie_metadata(title, encoded, year, quality, default_id):
    tmdb_id = int(default_id) if default_id and default_id.isdigit() else None

    if not tmdb_id:
        res = await safe_tmdb_search(title, "movie", year)
        if not res:
            return None
        tmdb_id = res.id

    async with API_SEMAPHORE:
        movie = await tmdb.movie(tmdb_id).details(append_to_response="external_ids,credits,images")

    return {
        "tmdb_id": movie.id,
        "imdb_id": getattr(movie.external_ids, "imdb_id", None),
        "title": movie.title,
        "year": movie.release_date.year if movie.release_date else 0,
        "rate": movie.vote_average or 0,
        "description": tr(movie.overview),
        "poster": format_tmdb_image(movie.poster_path),
        "backdrop": format_tmdb_image(movie.backdrop_path, "original"),
        "logo": get_tmdb_logo(movie.images),
        "genres": tur_genre_normalize([g.name for g in movie.genres]),
        "cast": [c.name for c in movie.credits.cast],
        "runtime": f"{movie.runtime} dk" if movie.runtime else "",
        "media_type": "movie",
        "quality": quality,
        "encoded_string": encoded,
    }
