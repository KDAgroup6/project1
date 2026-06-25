from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

LG_API_URL = "https://www.lgtwins.com/api/game/getGame"
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "lg_twins_schedule.db"
KST = ZoneInfo("Asia/Seoul")
DEFAULT_YEAR = datetime.now(KST).year


STADIUM_COORDS = {
    "잠실": {"lat": 37.5122, "lon": 127.0719},
    "잠실야구장": {"lat": 37.5122, "lon": 127.0719},
    "고척": {"lat": 37.4982, "lon": 126.8671},
    "고척스카이돔": {"lat": 37.4982, "lon": 126.8671},
    "문학": {"lat": 37.4369, "lon": 126.6933},
    "수원": {"lat": 37.2997, "lon": 127.0097},
    "대전": {"lat": 36.3171, "lon": 127.4292},
    "대구": {"lat": 35.8410, "lon": 128.6816},
    "광주": {"lat": 35.1682, "lon": 126.8888},
    "창원": {"lat": 35.2225, "lon": 128.5823},
    "사직": {"lat": 35.1940, "lon": 129.0615},
}


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_table() -> None:
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS games (
                gmkey TEXT PRIMARY KEY,
                game_date TEXT NOT NULL,
                game_time TEXT,
                weekday TEXT,
                stadium TEXT,
                home_team TEXT,
                away_team TEXT,
                opponent TEXT,
                is_home INTEGER,
                game_type TEXT,
                status TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_games_date ON games(game_date)")


def fetch_month(year: int, month: int) -> list[dict[str, Any]]:
    response = requests.post(
        LG_API_URL,
        data={"year": year, "month": month},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    response.encoding = "utf-8"
    response.raise_for_status()

    payload = response.json()
    if payload.get("code") != "OK":
        raise RuntimeError(payload.get("message", "LG 트윈스 일정 조회 실패"))

    return payload.get("data", {}).get("data", [])


def normalize_game(game: dict[str, Any]) -> dict[str, Any]:
    home_key = game.get("homeKey")
    visit_key = game.get("visitKey")
    is_home = home_key == "LG"

    opponent = game.get("visitName") if is_home else game.get("homeName")

    cancel_flag = game.get("cancelFlag")
    end_flag = game.get("endFlag")

    if cancel_flag == "1":
        status = "경기취소"
    elif end_flag == "1":
        status = "경기종료"
    else:
        status = "경기전"

    gamedate = str(game.get("gamedate", ""))
    game_date = f"{gamedate[:4]}-{gamedate[4:6]}-{gamedate[6:8]}"

    game_type = "시범경기" if game.get("gameFlag") == "1" else "정규경기"

    return {
        "gmkey": game.get("gmkey"),
        "game_date": game_date,
        "game_time": game.get("gtime", ""),
        "weekday": game.get("gweek", ""),
        "stadium": game.get("stadium", ""),
        "home_team": game.get("homeName", ""),
        "away_team": game.get("visitName", ""),
        "opponent": opponent or "",
        "is_home": 1 if is_home else 0,
        "game_type": game_type,
        "status": status,
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
    }


def save_games(games: list[dict[str, Any]]) -> int:
    normalized_games = [
        normalize_game(game)
        for game in games
        if game.get("gmkey")
        and (game.get("homeKey") == "LG" or game.get("visitKey") == "LG")
    ]

    with connect_db() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO games (
                gmkey, game_date, game_time, weekday, stadium,
                home_team, away_team, opponent, is_home,
                game_type, status, updated_at
            )
            VALUES (
                :gmkey, :game_date, :game_time, :weekday, :stadium,
                :home_team, :away_team, :opponent, :is_home,
                :game_type, :status, :updated_at
            )
            """,
            normalized_games,
        )

    return len(normalized_games)


def update_schedule_database(year: int = DEFAULT_YEAR) -> int:
    create_table()
    saved_count = 0

    for month in range(1, 13):
        try:
            month_games = fetch_month(year, month)
            saved_count += save_games(month_games)
        except Exception:
            pass

    return saved_count


def get_games_in_next_7_days() -> list[sqlite3.Row]:
    create_table()

    today = datetime.now(KST).date()
    end_date = today + timedelta(days=7)

    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM games
            WHERE game_date BETWEEN ? AND ?
            AND status != '경기취소'
            ORDER BY game_date, game_time, gmkey
            """,
            (today.isoformat(), end_date.isoformat()),
        ).fetchall()

    if not rows:
        update_schedule_database(DEFAULT_YEAR)

        with connect_db() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM games
                WHERE game_date BETWEEN ? AND ?
                AND status != '경기취소'
                ORDER BY game_date, game_time, gmkey
                """,
                (today.isoformat(), end_date.isoformat()),
            ).fetchall()

    return rows


def get_game_by_date(game_date: str) -> sqlite3.Row | None:
    create_table()

    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM games
            WHERE game_date = ?
            AND status != '경기취소'
            ORDER BY game_time, gmkey
            LIMIT 1
            """,
            (game_date,),
        ).fetchone()

    if row is None:
        update_schedule_database(DEFAULT_YEAR)
        with connect_db() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM games
                WHERE game_date = ?
                AND status != '경기취소'
                ORDER BY game_time, gmkey
                LIMIT 1
                """,
                (game_date,),
            ).fetchone()

    return row


def row_to_game(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "date": row["game_date"],
        "time": row["game_time"],
        "weekday": row["weekday"],
        "opponent": row["opponent"],
        "stadium": row["stadium"],
        "game_type": "홈경기" if row["is_home"] else "원정경기",
        "status": row["status"],
    }


def get_stadium_coord(stadium: str) -> dict[str, float]:
    for key, coord in STADIUM_COORDS.items():
        if key in stadium:
            return coord

    return STADIUM_COORDS["잠실야구장"]


def get_weather_api_data(stadium: str) -> dict[str, Any]:
    coord = get_stadium_coord(stadium)

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={coord['lat']}"
        f"&longitude={coord['lon']}"
        "&daily=temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max,precipitation_sum"
        "&timezone=Asia%2FSeoul"
    )

    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


def get_notice() -> list[str]:
    return [
        "날씨 예보는 오늘부터 약 7일 이내 날짜만 조회할 수 있어요.",
        "예보는 변경될 수 있으니 경기 당일 다시 확인해 주세요.",
        "강수확률이 높아도 실제 우천 취소 여부는 LG 트윈스 또는 KBO 공식 공지를 확인해 주세요.",
    ]


def get_llm_outfit_recommendation(game: dict[str, Any], weather: dict[str, Any]) -> str:
    prompt = f"""
너는 LG 트윈스 직관 초보자를 도와주는 친절한 챗봇이야.

아래 경기 정보와 날씨 정보를 바탕으로 복장과 준비물을 추천해줘.

날짜: {game["date"]} ({game["weekday"]})
상대 팀: {game["opponent"]}
경기장: {game["stadium"]}
홈/원정: {game["game_type"]}
경기 시간: {game["time"]}

최고 기온: {weather["max_temperature"]}도
최저 기온: {weather["min_temperature"]}도
평균 기온: {weather["average_temperature"]}도
강수확률: {weather["precipitation_probability"]}%
강수량: {weather["precipitation_sum"]}mm

조건:
- 평균 기온과 최저 기온을 함께 고려해줘.
- 야구장은 오래 앉아 있기 때문에 경기 후반 체감온도도 고려해줘.
- 강수확률이 60% 이상이면 우천 취소 가능성을 언급해줘.
- 반팔, 긴팔, 바람막이, 담요, 썬캡, 얼음물, 우비 등을 상황에 맞게 판단해줘.
- 초보 관람객에게 말하듯 자연스럽고 짧게 답해줘.

답변 형식:
1. 경기/날씨 요약
2. 추천 복장
3. 챙기면 좋은 준비물
4. 주의사항
"""

    response = client.responses.create(
        model="gpt-4o-mini",
        input=prompt,
    )

    return response.output_text


@app.get("/")
def home():
    return {
        "service": "LG 트윈스 직관 날씨 추천 API",
        "description": "LG 일정 DB가 비어 있으면 자동으로 일정을 갱신하고, 선택한 경기장의 날씨를 조회해 GPT가 복장을 추천합니다.",
        "notice": get_notice(),
        "menu": {
            "선택 가능한 경기 날짜": "/weather_dates/",
            "날씨 추천": "/weather/?date=YYYY-MM-DD",
        },
    }


@app.get("/weather_dates/")
def weather_dates():
    games = get_games_in_next_7_days()

    return {
        "message": "날씨 조회가 가능한 LG 경기 날짜를 선택해 주세요.",
        "notice": get_notice(),
        "available_dates": [row_to_game(row) for row in games],
    }


@app.get("/weather/")
def weather(date: str):
    row = get_game_by_date(date)

    if row is None:
        return {
            "error": "해당 날짜에는 등록된 LG 트윈스 경기가 없습니다.",
            "message": "먼저 /weather_dates/에서 선택 가능한 날짜를 확인해 주세요.",
            "notice": get_notice(),
        }

    game = row_to_game(row)
    weather_data = get_weather_api_data(game["stadium"])
    weather_dates = weather_data["daily"]["time"]

    if date not in weather_dates:
        return {
            "error": "날씨 조회 가능한 날짜가 아닙니다.",
            "message": "오늘부터 약 7일 이내 날짜만 실제 예보 조회가 가능해요.",
            "game": game,
            "notice": get_notice(),
        }

    index = weather_dates.index(date)

    max_temp = weather_data["daily"]["temperature_2m_max"][index]
    min_temp = weather_data["daily"]["temperature_2m_min"][index]
    precipitation_probability = weather_data["daily"]["precipitation_probability_max"][index]
    precipitation_sum = weather_data["daily"]["precipitation_sum"][index]
    avg_temp = round((max_temp + min_temp) / 2, 1)

    weather_result = {
        "location": game["stadium"],
        "max_temperature": max_temp,
        "min_temperature": min_temp,
        "average_temperature": avg_temp,
        "precipitation_probability": precipitation_probability,
        "precipitation_sum": precipitation_sum,
        "rain_cancel_warning": precipitation_probability >= 60,
    }

    llm_message = get_llm_outfit_recommendation(game, weather_result)

    return {
        "date": date,
        "game": game,
        "weather": weather_result,
        "llm_message": llm_message,
        "notice": get_notice(),
    }
