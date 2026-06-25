from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False

APP_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = APP_DIR / "frontend"
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "lg_twins_schedule.db"
LG_API_URL = "https://www.lgtwins.com/api/game/getGame"
BOOKING_LINK = "https://ticket.interpark.com"
KST = timezone(timedelta(hours=9), name="KST")
DEFAULT_MODEL = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")

load_dotenv(APP_DIR / "backend" / ".env", override=True)
DEFAULT_MODEL = os.getenv("OPENAI_DEFAULT_MODEL", DEFAULT_MODEL)

app = FastAPI(title="LG Twins Game Day Chatbot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI() if os.getenv("OPENAI_API_KEY") else None
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
KAKAO_LOCAL_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
NAVER_LOCAL_SEARCH_URL = "https://openapi.naver.com/v1/search/local.json"

STADIUM_COORDS = {
    "잠실": {"lat": 37.5122, "lon": 127.0719},
    "잠실야구장": {"lat": 37.5122, "lon": 127.0719},
    "고척": {"lat": 37.4982, "lon": 126.8671},
    "문학": {"lat": 37.4369, "lon": 126.6933},
    "수원": {"lat": 37.2997, "lon": 127.0097},
    "대전": {"lat": 36.3171, "lon": 127.4292},
    "대구": {"lat": 35.8410, "lon": 128.6816},
    "광주": {"lat": 35.1682, "lon": 126.8888},
    "창원": {"lat": 35.2225, "lon": 128.5823},
    "사직": {"lat": 35.1940, "lon": 129.0615},
}

class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []


def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
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
                dheader TEXT,
                game_type TEXT,
                status TEXT,
                lg_score INTEGER,
                opponent_score INTEGER,
                result TEXT,
                raw_home_key TEXT,
                raw_visit_key TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_games_date ON games(game_date)")


def fetch_month(year: int, month: int) -> list[dict[str, Any]]:
    data = urllib.parse.urlencode({"year": year, "month": month}).encode("utf-8")
    request = urllib.request.Request(
        LG_API_URL,
        data=data,
        headers={"User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != "OK":
        raise RuntimeError(payload.get("message", "LG 트윈스 일정 조회 실패"))
    return payload.get("data", {}).get("data", [])


def normalize_game(game: dict[str, Any]) -> dict[str, Any]:
    home_key = game.get("homeKey")
    visit_key = game.get("visitKey")
    is_home = home_key == "LG"
    opponent = game.get("visitName") if is_home else game.get("homeName")
    home_score = int(game.get("hscore") or 0)
    visit_score = int(game.get("vscore") or 0)
    lg_score = home_score if is_home else visit_score
    opponent_score = visit_score if is_home else home_score
    cancel_flag = game.get("cancelFlag")
    end_flag = game.get("endFlag")
    result = ""

    if cancel_flag == "1":
        status = "경기취소"
    elif end_flag == "1":
        status = "경기종료"
        result = "승" if lg_score > opponent_score else "패" if lg_score < opponent_score else "무"
    else:
        status = "경기전"

    gamedate = str(game.get("gamedate", ""))
    return {
        "gmkey": game.get("gmkey"),
        "game_date": f"{gamedate[:4]}-{gamedate[4:6]}-{gamedate[6:8]}",
        "game_time": game.get("gtime", ""),
        "weekday": game.get("gweek", ""),
        "stadium": game.get("stadium", ""),
        "home_team": game.get("homeName", ""),
        "away_team": game.get("visitName", ""),
        "opponent": opponent or "",
        "is_home": 1 if is_home else 0,
        "dheader": game.get("dheader", "0"),
        "game_type": "시범경기" if game.get("gameFlag") == "1" else "정규경기",
        "status": status,
        "lg_score": lg_score,
        "opponent_score": opponent_score,
        "result": result,
        "raw_home_key": home_key,
        "raw_visit_key": visit_key,
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
    }


def update_schedule_database(year: int | None = None) -> int:
    create_table()
    saved_count = 0
    target_year = year or datetime.now(KST).year
    for month in range(1, 13):
        try:
            games = [
                normalize_game(game)
                for game in fetch_month(target_year, month)
                if game.get("gmkey") and (game.get("homeKey") == "LG" or game.get("visitKey") == "LG")
            ]
            with connect_db() as conn:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO games (
                        gmkey, game_date, game_time, weekday, stadium, home_team, away_team,
                        opponent, is_home, dheader, game_type, status, lg_score, opponent_score,
                        result, raw_home_key, raw_visit_key, updated_at
                    )
                    VALUES (
                        :gmkey, :game_date, :game_time, :weekday, :stadium, :home_team, :away_team,
                        :opponent, :is_home, :dheader, :game_type, :status, :lg_score, :opponent_score,
                        :result, :raw_home_key, :raw_visit_key, :updated_at
                    )
                    """,
                    games,
                )
            saved_count += len(games)
        except Exception:
            continue
    return saved_count


def parse_date(text: str) -> str | None:
    today = datetime.now(KST).date()
    compact = re.sub(r"\s+", "", text).lower()
    relative = {"오늘": 0, "내일": 1, "모레": 2, "어제": -1}
    for word, delta in relative.items():
        if word in compact:
            return (today + timedelta(days=delta)).isoformat()
    if "today" in compact:
        return today.isoformat()
    if "tomorrow" in compact:
        return (today + timedelta(days=1)).isoformat()

    match = re.search(r"(20\d{2})[-./년]*(\d{1,2})[-./월]*(\d{1,2})", compact)
    if match:
        year, month, day = map(int, match.groups())
        return date(year, month, day).isoformat()

    match = re.search(r"(\d{1,2})[-./월](\d{1,2})", compact)
    if match:
        month, day = map(int, match.groups())
        return date(today.year, month, day).isoformat()
    return None


def available_game_dates(year: int | None = None) -> list[dict[str, Any]]:
    create_table()
    target_year = str(year or datetime.now(KST).year)
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT game_date, weekday, game_time, stadium, opponent, is_home, status
            FROM games
            WHERE substr(game_date, 1, 4) = ?
            ORDER BY game_date, game_time, gmkey
            """,
            (target_year,),
        ).fetchall()
    if not rows:
        update_schedule_database(int(target_year))
        return available_game_dates(int(target_year))
    return [dict(row) for row in rows]


def row_to_game(row: sqlite3.Row) -> dict[str, Any]:
    game = dict(row)
    game["home_or_away"] = "홈" if game.get("is_home") else "원정"
    return game


def format_game(row: sqlite3.Row) -> str:
    home_or_away = "홈" if row["is_home"] else "원정"
    lines = [
        f"{row['game_date']}({row['weekday']}) {row['game_time']} LG 트윈스 vs {row['opponent']}",
        f"장소: {row['stadium']} / 구분: {home_or_away} {row['game_type']} / 상태: {row['status']}",
    ]
    if row["status"] == "경기종료":
        lines.append(f"결과: LG {row['lg_score']} : {row['opponent_score']} {row['opponent']} ({row['result']})")
    return "\n".join(lines)


# TOOL 1. 경기 일정 조회
# LG 트윈스 일정 DB에서 날짜/이번 주/주말 조건에 맞는 경기 정보를 찾아 챗봇에 넘깁니다.
def get_lg_twins_schedule(query: str = "", game_date: str | None = None) -> dict[str, Any]:
    create_table()
    target_date = game_date or parse_date(query)
    today = datetime.now(KST).date()
    compact_query = re.sub(r"\s+", "", query)

    if "주말" in compact_query:
        start = today + timedelta(days=(5 - today.weekday()) % 7)
        end = start + timedelta(days=1)
    elif "이번주" in compact_query:
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif target_date:
        start = end = date.fromisoformat(target_date)
    else:
        start = today
        end = today + timedelta(days=14)

    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM games
            WHERE game_date BETWEEN ? AND ?
            ORDER BY game_date, game_time, gmkey
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    if not rows:
        update_schedule_database(start.year)
        with connect_db() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM games
                WHERE game_date BETWEEN ? AND ?
                ORDER BY game_date, game_time, gmkey
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()

    return {
        "tool_name": "get_lg_twins_schedule",
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "games": [row_to_game(row) for row in rows],
        "summary": "\n\n".join(format_game(row) for row in rows) if rows else "해당 기간에는 등록된 LG 트윈스 경기가 없습니다.",
    }


# TOOL 2. 예매/좌석 안내
# 예매 키워드가 있으면 예매 단계를, 좌석 키워드가 있으면 좌석 추천용 데이터를 반환합니다.
def get_booking_intent(topic: str) -> str:
    compact = re.sub(r"\s+", "", topic)
    has_booking = any(word in compact for word in ["예매", "티켓", "인터파크", "결제", "입장권", "예약"])
    has_seat = any(word in compact for word in ["좌석", "자리", "내야", "외야", "응원석", "어디서", "구역", "시야"])

    if has_booking and has_seat:
        return "booking_and_seat"
    if has_seat:
        return "seat"
    return "booking"


def guide_lg_twins_booking(topic: str = "예매") -> dict[str, Any]:
    intent = get_booking_intent(topic)
    return {
        "tool_name": "guide_lg_twins_booking",
        "intent": intent,
        "booking_link": BOOKING_LINK,
        "steps": [
            "인터파크 티켓에서 LG 트윈스 경기를 검색합니다.",
            "원하는 날짜와 경기 정보를 확인합니다. 원정 경기는 상대 구단 예매처를 확인해야 합니다.",
            "내야, 외야, 응원석 중 관람 스타일에 맞는 구역을 고릅니다.",
            "결제 후 모바일 티켓 또는 QR 입장권을 확인합니다.",
        ],
        "seat_tips": {
            "infield": "경기를 가까이 보고 싶고 시야를 중시하면 내야석이 좋아요.",
            "outfield": "가격 부담을 낮추고 편하게 보고 싶으면 외야석이 좋아요.",
            "cheer": "응원 분위기를 제대로 느끼고 싶으면 응원석이 좋아요.",
        },
        "notice": "실시간 잔여석과 가격은 공식 예매처에서 확인해 주세요.",
    }


def stadium_coord(stadium: str) -> dict[str, float]:
    for key, coord in STADIUM_COORDS.items():
        if key in stadium:
            return coord
    return STADIUM_COORDS["잠실야구장"]


# TOOL 3. 날씨 기반 복장 추천
# 선택한 경기장의 Open-Meteo 예보를 가져오고, 기온/강수확률에 맞는 복장을 추천합니다.
def recommend_outfit_locally(weather: dict[str, Any]) -> str:
    avg = weather["average_temperature"]
    rain = weather["precipitation_probability"]
    outfit = "반팔 또는 얇은 셔츠"
    if avg < 12:
        outfit = "니트나 맨투맨에 따뜻한 외투"
    elif avg < 18:
        outfit = "긴팔에 가벼운 바람막이"
    elif avg < 24:
        outfit = "얇은 긴팔이나 반팔에 걸칠 셔츠"
    elif avg >= 28:
        outfit = "통풍 좋은 반팔과 모자"
    extras = ["보조배터리", "물"]
    if rain >= 50:
        extras.extend(["우비", "방수 가방"])
    if avg < 18:
        extras.append("작은 담요")
    return f"평균 {avg}도 기준으로 {outfit}을 추천해요. 준비물은 {', '.join(extras)}가 좋아요."


def recommend_outfit_by_weather(game_date: str | None = None, query: str = "") -> dict[str, Any]:
    target_date = game_date or parse_date(query)
    if not target_date:
        return {"tool_name": "recommend_outfit_by_weather", "error": "복장 추천을 받을 경기 날짜를 먼저 알려 주세요."}

    schedule = get_lg_twins_schedule(game_date=target_date)
    if not schedule["games"]:
        return {"tool_name": "recommend_outfit_by_weather", "error": f"{target_date}에는 등록된 LG 트윈스 경기가 없습니다."}

    game = schedule["games"][0]
    coord = stadium_coord(game["stadium"])
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={coord['lat']}&longitude={coord['lon']}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum"
        "&timezone=Asia%2FSeoul"
    )
    with urllib.request.urlopen(url, timeout=10) as response:
        daily = json.loads(response.read().decode("utf-8"))["daily"]
    if target_date not in daily["time"]:
        return {
            "tool_name": "recommend_outfit_by_weather",
            "game": game,
            "error": "날씨 예보는 오늘부터 약 7일 이내 경기만 조회할 수 있어요.",
        }

    index = daily["time"].index(target_date)
    max_temp = daily["temperature_2m_max"][index]
    min_temp = daily["temperature_2m_min"][index]
    weather = {
        "location": game["stadium"],
        "max_temperature": max_temp,
        "min_temperature": min_temp,
        "average_temperature": round((max_temp + min_temp) / 2, 1),
        "precipitation_probability": daily["precipitation_probability_max"][index],
        "precipitation_sum": daily["precipitation_sum"][index],
    }
    return {
        "tool_name": "recommend_outfit_by_weather",
        "game": game,
        "weather": weather,
        "local_recommendation": recommend_outfit_locally(weather),
        "notice": "강수확률이 높아도 실제 우천 취소 여부는 구단/KBO 공지를 확인해 주세요.",
    }


def search_kakao_local(query: str, lat: float, lon: float, radius: int, limit: int = 5) -> list[dict[str, Any]]:
    if not KAKAO_REST_API_KEY:
        return []
    params = urllib.parse.urlencode(
        {"query": query, "x": lon, "y": lat, "radius": radius, "sort": "distance", "size": limit}
    )
    request = urllib.request.Request(
        f"{KAKAO_LOCAL_SEARCH_URL}?{params}",
        headers={"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    return payload.get("documents", [])


def search_naver_local(query: str, limit: int = 5) -> list[dict[str, Any]]:
    if not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET):
        return []
    params = urllib.parse.urlencode({"query": query, "display": limit, "sort": "comment"})
    request = urllib.request.Request(
        f"{NAVER_LOCAL_SEARCH_URL}?{params}",
        headers={
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    return payload.get("items", [])


def search_naver_local_multi(queries: list[str], limit: int = 5) -> list[dict[str, Any]]:
    for query in queries:
        items = search_naver_local(query, limit=limit)
        if items:
            return items
    return []


def format_kakao_place(place: dict[str, Any]) -> dict[str, str]:
    category_tail = (place.get("category_name") or "").split(">")[-1].strip() or "음식점"
    distance = place.get("distance")
    address = place.get("road_address_name") or place.get("address_name") or "주소 확인 필요"
    location = f"{address} (잠실야구장에서 약 {int(distance):,}m)" if distance else address
    reason = f"카카오맵 기준 {category_tail} 매장이에요."
    phone = place.get("phone")
    if phone:
        reason += f" 문의: {phone}"
    return {"name": place.get("place_name", "이름 확인 필요"), "menu": category_tail, "location": location, "reason": reason}


def format_naver_place(place: dict[str, Any]) -> dict[str, str]:
    name = re.sub(r"</?b>", "", place.get("title", "이름 확인 필요"))
    category = place.get("category") or "음식점"
    address = place.get("roadAddress") or place.get("address") or "주소 확인 필요"
    reason = f"네이버 검색 기준 {category} 매장이에요."
    if place.get("telephone"):
        reason += f" 문의: {place['telephone']}"
    return {"name": name, "menu": category, "location": address, "reason": reason}


# 야구장 내부 매점은 지도 API에 음식점으로 등록되지 않는 경우가 많아 검색이 신뢰할 수 없다.
# 직접 확인한 매장만 고정 목록으로 관리해 항상 정확한 정보를 준다.
INSIDE_STADIUM_FOOD = [
    {
        "name": "잠실 원샷치킨",
        "condition": "든든한 식사",
        "menu": "치킨, 감자튀김, 콤보 메뉴",
        "location": "3루 방향 내부 매장 구역",
        "reason": "여러 명이 함께 나누어 먹기 좋아요.",
    },
    {
        "name": "버거앤프라이즈 잠실야구장점",
        "condition": "든든한 식사",
        "menu": "햄버거 세트",
        "location": "중앙 출입구 인근",
        "reason": "경기 시작 전에 빠르게 식사하기 좋아요.",
    },
    {
        "name": "스테프핫도그",
        "condition": "간단한 간식",
        "menu": "핫도그, 소시지",
        "location": "1루 방향 내부 매장 구역",
        "reason": "한 손으로 들고 먹기 편해요.",
    },
    {
        "name": "잠실야구장 분식 매장",
        "condition": "인기 음식",
        "menu": "떡볶이, 튀김, 닭강정",
        "location": "3루 내야 출입구 인근",
        "reason": "야구장에서 가볍게 즐기기 좋은 인기 메뉴예요.",
    },
]


def recommend_inside_stadium_food(condition: str) -> dict[str, Any]:
    matches = [item for item in INSIDE_STADIUM_FOOD if item["condition"] == condition] or INSIDE_STADIUM_FOOD
    restaurants = [{k: v for k, v in item.items() if k != "condition"} for item in matches]
    return {
        "tool_name": "recommend_jamsil_food",
        "source": "curated_list",
        "place": "inside",
        "condition": condition,
        "cuisine": None,
        "restaurants": restaurants,
        "notice": "매장 입점 여부와 메뉴는 변경될 수 있으니 방문 전 확인해 주세요.",
    }


# TOOL 4. 음식점 추천
# 외부 맛집은 카카오/네이버 로컬 검색 API로 실제 등록된 업체만 찾아 추천한다 (LLM이 이름을 지어내지 않음).
# 내부 매점은 위 고정 목록(INSIDE_STADIUM_FOOD)을 사용한다.
def search_jamsil_food(place: str, condition: str, cuisine: str | None = None) -> dict[str, Any]:
    if place == "inside":
        return recommend_inside_stadium_food(condition)

    coord = STADIUM_COORDS["잠실야구장"]
    cuisine_label = f"{cuisine} " if cuisine and cuisine != "기타" else ""
    kakao_query = f"잠실 {cuisine_label}맛집".strip()
    naver_queries = [
        f"잠실야구장 근처 {cuisine_label}맛집".strip(),
        f"잠실새내 {cuisine_label}맛집".strip(),
        f"잠실 {cuisine_label}맛집".strip(),
    ]
    radius = 1500

    documents = search_kakao_local(kakao_query, coord["lat"], coord["lon"], radius=radius)
    if documents:
        restaurants = [format_kakao_place(doc) for doc in documents[:5]]
        source = "kakao_local"
    else:
        items = search_naver_local_multi(naver_queries)
        restaurants = [format_naver_place(item) for item in items[:5]]
        source = "naver_local" if restaurants else "no_results"

    notice = (
        "지도 검색 기준 정보이며, 영업 시간과 메뉴는 방문 전 확인해 주세요."
        if restaurants
        else "조건에 맞는 음식점을 찾지 못했습니다. 다른 음식 종류로 다시 물어봐 주세요."
    )

    return {
        "tool_name": "recommend_jamsil_food",
        "source": source,
        "place": place,
        "condition": condition,
        "cuisine": cuisine,
        "restaurants": restaurants,
        "notice": notice,
    }


CUISINE_KEYWORDS = {
    "한식": ["한식", "한정식", "국밥", "찌개", "백반", "고기", "삼겹살"],
    "일식": ["일식", "초밥", "스시", "라멘", "돈카츠", "우동"],
    "양식": ["양식", "파스타", "피자", "스테이크", "버거"],
    "중식": ["중식", "짜장", "짬뽕", "탕수육", "마라"],
}


def detect_cuisine(query: str) -> str | None:
    compact = re.sub(r"\s+", "", query)
    for cuisine, keywords in CUISINE_KEYWORDS.items():
        if any(word in compact for word in keywords):
            return cuisine
    if any(word in compact for word in ["기타", "상관없", "아무거나"]):
        return "기타"
    return None


def recommend_jamsil_food(
    place: str | None = None,
    timing_or_category: str | None = None,
    query: str = "",
    cuisine: str | None = None,
) -> dict[str, Any]:
    compact = re.sub(r"\s+", "", query)
    selected_place = place
    condition = timing_or_category
    selected_cuisine = cuisine or detect_cuisine(query)

    if not selected_place:
        selected_place = "outside" if any(word in compact for word in ["근처", "주변", "밖", "경기전", "경기후"]) else "inside"
    if not condition:
        if any(word in compact for word in ["경기후", "끝나고", "종료후"]):
            condition = "경기 후"
        elif any(word in compact for word in ["경기전", "시작전"]):
            condition = "경기 전"
        elif any(word in compact for word in ["간식", "핫도그", "가볍"]):
            condition = "간단한 간식"
        elif any(word in compact for word in ["인기", "떡볶이", "닭강정"]):
            condition = "인기 음식"
        else:
            condition = "든든한 식사" if selected_place == "inside" else "경기 전"

    if selected_place == "outside" and not (KAKAO_REST_API_KEY or (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET)):
        return {
            "tool_name": "recommend_jamsil_food",
            "source": "search_unavailable",
            "place": selected_place,
            "condition": condition,
            "cuisine": selected_cuisine,
            "restaurants": [],
            "notice": "주변 맛집 검색은 카카오 또는 네이버 로컬 검색 키가 필요합니다. KAKAO_REST_API_KEY나 NAVER_CLIENT_ID/SECRET을 설정한 뒤 다시 시도해 주세요.",
        }

    try:
        return search_jamsil_food(selected_place, condition, selected_cuisine)
    except Exception as exc:
        return {
            "tool_name": "recommend_jamsil_food",
            "source": "search_error",
            "place": selected_place,
            "condition": condition,
            "cuisine": selected_cuisine,
            "restaurants": [],
            "notice": f"음식점 검색 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요. ({exc})",
        }


TOOLS = [
    {
        "type": "function",
        "name": "get_lg_twins_schedule",
        "description": "LG 트윈스 경기 일정, 경기 시간, 장소, 상대팀, 결과를 조회합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "사용자의 일정 질문 원문"},
                "game_date": {"type": ["string", "null"], "description": "YYYY-MM-DD 형식의 특정 경기 날짜"},
            },
            "required": ["query", "game_date"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "guide_lg_twins_booking",
        "description": "LG 트윈스 경기 예매 방법 또는 좌석 선택 팁을 안내합니다. 좌석 질문만 있으면 예매 절차를 길게 안내하지 않습니다.",
        "parameters": {
            "type": "object",
            "properties": {"topic": {"type": "string", "description": "예매 또는 좌석 관련 질문 주제"}},
            "required": ["topic"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "recommend_outfit_by_weather",
        "description": "선택한 경기 날짜의 경기장 날씨를 조회하고 직관 복장을 추천합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "game_date": {"type": ["string", "null"], "description": "YYYY-MM-DD 형식의 경기 날짜"},
                "query": {"type": "string", "description": "사용자의 복장/날씨 질문 원문"},
            },
            "required": ["game_date", "query"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "recommend_jamsil_food",
        "description": "잠실야구장 내부 음식점 또는 경기장 주변 맛집을 추천합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "place": {"type": ["string", "null"], "enum": ["inside", "outside", None]},
                "timing_or_category": {
                    "type": ["string", "null"],
                    "description": "경기 전, 경기 후, 든든한 식사, 간단한 간식, 인기 음식 중 하나",
                },
                "cuisine": {
                    "type": ["string", "null"],
                    "enum": ["한식", "일식", "양식", "중식", "기타", None],
                    "description": "사용자가 원하는 음식 종류. 사용자가 먼저 말하지 않았다면 도구를 호출하기 전에 반드시 한 번 물어봐야 함",
                },
                "query": {"type": "string", "description": "사용자의 음식 추천 질문 원문"},
            },
            "required": ["place", "timing_or_category", "cuisine", "query"],
            "additionalProperties": False,
        },
    },
]

TOOL_HANDLERS = {
    "get_lg_twins_schedule": get_lg_twins_schedule,
    "guide_lg_twins_booking": guide_lg_twins_booking,
    "recommend_outfit_by_weather": recommend_outfit_by_weather,
    "recommend_jamsil_food": recommend_jamsil_food,
}

SYSTEM_PROMPT = """
너는 LG 트윈스 직관 준비를 도와주는 대화형 챗봇 '트윈스봇'이야.
오늘 날짜는 {today}이고, 시간대는 한국 시간(KST)이야.
사용자가 '오늘' 또는 'today'라고 말하면 반드시 {today}로 해석해.
사용자의 질문을 보고 필요한 도구를 골라 경기 일정, 예매, 날씨 기반 복장, 잠실 먹거리를 안내해.
답변은 한국어로 짧고 친절하게 작성하고, 모르는 정보는 확정하지 말고 공식 확인이 필요하다고 말해.
이번 주, 다음 주, 오늘 같은 상대 날짜 표현은 오늘 날짜를 기준으로 해석해.
예매 방법은 사용자가 예매, 티켓, 인터파크, 결제, 입장권처럼 예매 관련 키워드를 말했을 때만 안내해.
좌석, 자리, 내야, 외야, 응원석 질문은 좌석 선택 팁 중심으로 답하고 예매 절차는 덧붙이지 마.
음식점 질문을 받으면 사용자가 음식 종류(한식/일식/양식/중식/기타)를 아직 말하지 않았다면 도구를 호출하기 전에 먼저 그것부터 물어봐.
음식 종류를 알게 되면 recommend_jamsil_food 도구를 사용해 검색 기반으로 5개를 추천해.
대화 기록을 참고하되, 앱이 종료되면 기록은 사라지는 임시 기억이라고 생각해.
"""


def fallback_tool_for(message: str) -> tuple[str, dict[str, Any]]:
    compact = re.sub(r"\s+", "", message)
    if any(word in compact for word in ["날씨", "기온", "온도", "복장", "옷", "입고"]):
        return "recommend_outfit_by_weather", {"game_date": parse_date(message), "query": message}
    if any(word in compact for word in ["음식", "먹", "맛집", "간식", "치킨", "떡볶이", "핫도그"]):
        return "recommend_jamsil_food", {"place": None, "timing_or_category": None, "cuisine": None, "query": message}
    if any(word in compact for word in ["예매", "티켓", "좌석", "자리", "인터파크"]):
        return "guide_lg_twins_booking", {"topic": message}
    return "get_lg_twins_schedule", {"query": message, "game_date": parse_date(message)}


def local_answer(tool_name: str, tool_result: dict[str, Any]) -> str:
    if tool_name == "get_lg_twins_schedule":
        return tool_result["summary"]
    if tool_name == "guide_lg_twins_booking":
        intent = tool_result.get("intent", "booking")
        if intent == "seat":
            tips = tool_result["seat_tips"]
            return (
                "좌석은 관람 스타일에 맞춰 고르면 좋아요.\n\n"
                f"- 내야석: {tips['infield']}\n"
                f"- 외야석: {tips['outfield']}\n"
                f"- 응원석: {tips['cheer']}\n\n"
                "원하는 분위기를 말해주면 더 좁혀서 추천해드릴게요."
            )
        steps = "\n".join(f"{i}. {step}" for i, step in enumerate(tool_result["steps"], start=1))
        return f"예매는 인터파크 티켓에서 진행하면 돼요.\n\n{steps}\n\n예매 링크: {tool_result['booking_link']}"
    if tool_name == "recommend_outfit_by_weather":
        if "error" in tool_result:
            return tool_result["error"]
        weather = tool_result["weather"]
        return (
            f"{tool_result['game']['game_date']} {tool_result['game']['stadium']}은 "
            f"최고 {weather['max_temperature']}도, 최저 {weather['min_temperature']}도, "
            f"강수확률 {weather['precipitation_probability']}%예요.\n"
            f"{tool_result['local_recommendation']}\n{tool_result['notice']}"
        )
    restaurants = tool_result.get("restaurants", [])
    if not restaurants:
        return tool_result.get("notice", "음식점 검색 결과가 없습니다. 잠시 후 다시 시도해 주세요.")
    lines = [
        f"{item['name']} - {item['menu']} ({item['location']})\n추천 이유: {item['reason']}"
        for item in restaurants
    ]
    return "\n\n".join(lines) + f"\n\n{tool_result['notice']}"


@app.get("/api/calendar-dates")
def calendar_dates(year: int | None = None):
    return {"dates": available_game_dates(year)}


@app.post("/api/chat")
def chat(request: ChatRequest):
    message = request.message.strip()
    if not message:
        return {"answer": "질문을 입력해 주세요.", "tool": None, "tool_result": None, "link": BOOKING_LINK}

    if client is None:
        tool_name, args = fallback_tool_for(message)
        tool_result = TOOL_HANDLERS[tool_name](**args)
        return {"answer": local_answer(tool_name, tool_result), "tool": tool_name, "tool_result": tool_result, "link": BOOKING_LINK}

    system_prompt = SYSTEM_PROMPT.format(today=datetime.now(KST).date().isoformat())
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for turn in request.history[-12:]:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": f"{message}\n\n[현재 날짜: {datetime.now(KST).date().isoformat()} / 시간대: KST]"})

    try:
        first = client.responses.create(
            model=DEFAULT_MODEL,
            input=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
            max_output_tokens=700,
        )
        function_calls = [item for item in first.output if item.type == "function_call"]
        if not function_calls:
            return {"answer": first.output_text, "tool": None, "tool_result": None, "link": BOOKING_LINK}

        tool_outputs = []
        last_tool_name = None
        last_tool_result = None
        for call in function_calls:
            args = json.loads(call.arguments or "{}")
            last_tool_name = call.name
            last_tool_result = TOOL_HANDLERS[call.name](**args)
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(last_tool_result, ensure_ascii=False),
                }
            )

        final = client.responses.create(
            model=DEFAULT_MODEL,
            previous_response_id=first.id,
            input=tool_outputs,
            temperature=0.3,
            max_output_tokens=900,
        )
        return {
            "answer": final.output_text,
            "tool": last_tool_name,
            "tool_result": last_tool_result,
            "link": BOOKING_LINK,
        }
    except Exception as exc:
        tool_name, args = fallback_tool_for(message)
        tool_result = TOOL_HANDLERS[tool_name](**args)
        return {
            "answer": local_answer(tool_name, tool_result),
            "tool": tool_name,
            "tool_result": tool_result,
            "link": BOOKING_LINK,
            "warning": f"OpenAI 도구 선택 중 문제가 있어 기본 분류로 답했어요: {exc}",
        }


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
