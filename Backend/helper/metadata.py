import asyncio
import re
from cachetools import TTLCache
from PTN import parse as ptn_parse
from imdb import Cinemagoer
from tmdbv3api import TMDb, Movie, TV, Search

# ================= TMDB CONFIG =================
tmdb = TMDb()
tmdb.api_key = "TMDB_API_KEYIN"
tmdb.language = "en"

tmdb_movie = Movie()
tmdb_tv = TV()
tmdb_search = Search()

imdb = Cinemagoer()

API_SEMAPHORE = asyncio.Semaphore(12)

# ================= CACHE =================
IMDB_CACHE = TTLCache(maxsize=3000, ttl=3600)
TMDB_DETAILS_CACHE = TTLCache(maxsize=3000, ttl=3600)
TMDB_SEARCH_CACHE = TTLCache(maxsize=3000, ttl=3600)
EPISODE_CACHE = TTLCache(maxsize=5000, ttl=3600)

# ================= GENRE MAP =================
TMDB_GENRE_MAP = {
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

# ================= PLATFORM MAP =================
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

# ================= HELPERS =================
def normalize_tmdb_genres(tmdb_genres):
    genres = []
    for g in tmdb_genres or []:
        name = g["name"] if isinstance(g, dict) else str(g)
        tr = TMDB_GENRE_MAP.get(name, name)
        if tr not in genres:
            genres.append(tr)
    return genres


def inject_platforms(genres, telegram_names):
    for name in telegram_names or []:
        low = name.lower()
        for key, platform in PLATFORM_MAP.items():
            if key in low and platform not in genres:
                genres.append(platform)
    return genres


def build_final_genres(tmdb_genres, telegram_files):
    genres = normalize_tmdb_genres(tmdb_genres)
    return inject_platforms(genres, telegram_files)


def clean_filename(name: str):
    return re.sub(r"[._]+", " ", name).strip()


# ================= TMDB FETCH =================
async def tmdb_movie_details(movie_id):
    if movie_id in TMDB_DETAILS_CACHE:
        return TMDB_DETAILS_CACHE[movie_id]

    async with API_SEMAPHORE:
        details = await asyncio.to_thread(
            tmdb_movie.details,
            movie_id,
            append_to_response="external_ids,credits,images"
        )
        TMDB_DETAILS_CACHE[movie_id] = details
        return details


async def tmdb_tv_details(tv_id):
    if tv_id in TMDB_DETAILS_CACHE:
        return TMDB_DETAILS_CACHE[tv_id]

    async with API_SEMAPHORE:
        details = await asyncio.to_thread(
            tmdb_tv.details,
            tv_id,
            append_to_response="external_ids,credits,images"
        )
        TMDB_DETAILS_CACHE[tv_id] = details
        return details


# ================= MAIN METADATA =================
async def extract_metadata(filename, telegram_files):
    parsed = ptn_parse(filename)
    title = parsed.get("title")
    year = parsed.get("year")
    is_tv = bool(parsed.get("season"))

    telegram_names = [f["name"] for f in telegram_files]

    if is_tv:
        return await build_tv_metadata(title, year, telegram_names)
    else:
        return await build_movie_metadata(title, year, telegram_names)


# ================= MOVIE =================
async def build_movie_metadata(title, year, telegram_names):
    query_key = f"{title}_{year}"
    if query_key in TMDB_SEARCH_CACHE:
        result = TMDB_SEARCH_CACHE[query_key]
    else:
        async with API_SEMAPHORE:
            res = await asyncio.to_thread(
                tmdb_search.movies,
                {"query": title, "year": year}
            )
            result = res[0] if res else None
            TMDB_SEARCH_CACHE[query_key] = result

    if not result:
        return None

    movie = await tmdb_movie_details(result.id)

    genres = build_final_genres(movie.genres, telegram_names)

    return {
        "type": "movie",
        "title": movie.title,
        "original_title": movie.original_title,
        "year": int(movie.release_date[:4]) if movie.release_date else None,
        "tmdb_id": int(movie.id),
        "imdb_id": movie.external_ids.get("imdb_id"),
        "rating": movie.vote_average,
        "overview": movie.overview,
        "runtime": movie.runtime,
        "genres": genres,
        "cast": [c.name for c in movie.credits.get("cast", [])[:10]],
    }


# ================= TV =================
async def build_tv_metadata(title, year, telegram_names):
    query_key = f"{title}_{year}"
    if query_key in TMDB_SEARCH_CACHE:
        result = TMDB_SEARCH_CACHE[query_key]
    else:
        async with API_SEMAPHORE:
            res = await asyncio.to_thread(
                tmdb_search.tv,
                {"query": title, "first_air_date_year": year}
            )
            result = res[0] if res else None
            TMDB_SEARCH_CACHE[query_key] = result

    if not result:
        return None

    tv = await tmdb_tv_details(result.id)

    genres = build_final_genres(tv.genres, telegram_names)

    return {
        "type": "tv",
        "name": tv.name,
        "original_name": tv.original_name,
        "year": int(tv.first_air_date[:4]) if tv.first_air_date else None,
        "tmdb_id": int(tv.id),
        "imdb_id": tv.external_ids.get("imdb_id"),
        "rating": tv.vote_average,
        "overview": tv.overview,
        "genres": genres,
        "cast": [c.name for c in tv.credits.get("cast", [])[:10]],
        "seasons": [],
    }
