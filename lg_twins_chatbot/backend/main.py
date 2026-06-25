"""
==============================================================================
 LG 트윈스 직관 도우미 챗봇 (FastAPI + OpenAI Function Calling)  — 발표용 주석본
==============================================================================

[ 한 줄 소개 ]
 - 사용자가 한국어로 질문하면, OpenAI 모델이 "어떤 기능(도구)을 써야 할지" 스스로
   판단하고, 백엔드에 미리 만들어 둔 4개의 도구를 호출해 실제 데이터를 가져온 뒤
   친절한 한국어 답변으로 정리해 주는 챗봇 서버다.

[ 4개의 도구(Tool) ]
   TOOL 1. 경기 일정 조회      → LG 트윈스 공식 API + SQLite DB
   TOOL 2. 예매 / 좌석 안내     → 예매 절차 / 좌석 선택 팁
   TOOL 3. 날씨 기반 복장 추천  → Open-Meteo 날씨 API
   TOOL 4. 잠실 음식점 추천     → 카카오 / 네이버 로컬 검색 API + 내부 매점 고정 목록

[ 핵심 설계 포인트 — 발표에서 강조할 부분 ]
 1) "LLM이 정보를 지어내지 않게" 한다. → 일정/날씨/맛집은 전부 실제 API·DB에서 가져온다.
 2) OpenAI 키가 없거나 호출에 실패해도 동작하도록 "Fallback(대체 분류)" 로직을 둔다.
 3) 도구의 입력/출력 형식을 JSON Schema(TOOLS)로 명확히 정의해 모델이 정확히 호출하게 한다.
==============================================================================
"""

from __future__ import annotations  # 타입 힌트를 더 유연하게 쓰기 위한 미래 기능 설정

# ── 표준 라이브러리 ───────────────────────────────────────────────────────────
import json                      # JSON 문자열 <-> 파이썬 객체 변환
import os                        # 환경변수(API 키 등) 읽기
import re                        # 정규표현식(문자 패턴 찾기)
import sqlite3                   # 가벼운 파일 기반 데이터베이스
import urllib.parse              # URL 인코딩(쿼리 파라미터 조립)
import urllib.request            # 외부 API HTTP 요청
from datetime import date, datetime, timedelta, timezone  # 날짜/시간 계산
from pathlib import Path         # 파일·폴더 경로를 다루는 최신 방식
from typing import Any, Literal  # 타입 힌트 (Any=아무 타입, Literal=정해진 값만)

# ── 외부 라이브러리 ───────────────────────────────────────────────────────────
from fastapi import FastAPI                       # 웹 API 서버 프레임워크
from fastapi.middleware.cors import CORSMiddleware  # 다른 도메인에서 호출 허용(CORS)
from fastapi.staticfiles import StaticFiles       # HTML/CSS/JS 같은 정적 파일 제공
from openai import OpenAI                          # OpenAI 모델 호출 클라이언트
from pydantic import BaseModel                     # 요청 본문 검증용 데이터 모델

# .env 파일에서 비밀 키를 불러오는 기능 (없어도 앱이 죽지 않도록 예외 처리)
try:
    from dotenv import load_dotenv
except ImportError:
    # python-dotenv가 설치돼 있지 않으면, 아무 일도 안 하는 가짜 함수로 대체한다.
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False


# ==============================================================================
# 1. 전역 설정 (경로 / 외부 주소 / 시간대 / 모델명)
# ==============================================================================
APP_DIR = Path(__file__).resolve().parent.parent  # 프로젝트 최상위 폴더
FRONTEND_DIR = APP_DIR / "frontend"               # 화면(HTML 등)이 들어 있는 폴더
DATA_DIR = APP_DIR / "data"                        # DB 파일을 저장할 폴더
DB_PATH = DATA_DIR / "lg_twins_schedule.db"        # SQLite DB 파일 위치
LG_API_URL = "https://www.lgtwins.com/api/game/getGame"  # LG 공식 일정 API
BOOKING_LINK = "https://ticket.interpark.com"      # 예매 안내 링크
KST = timezone(timedelta(hours=9), name="KST")     # 한국 시간대(UTC+9)
DEFAULT_MODEL = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")  # 사용할 모델

# backend/.env 파일을 읽어 환경변수를 채우고, 모델명을 한 번 더 갱신한다.
load_dotenv(APP_DIR / "backend" / ".env", override=True)
DEFAULT_MODEL = os.getenv("OPENAI_DEFAULT_MODEL", DEFAULT_MODEL)


# ==============================================================================
# 2. FastAPI 앱 생성 및 CORS 설정
#    - CORS: 프론트엔드(브라우저)가 다른 주소에서 이 API를 호출할 수 있게 허용한다.
# ==============================================================================
app = FastAPI(title="LG Twins Game Day Chatbot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # 모든 출처 허용 (발표/실습용 설정)
    allow_credentials=False,
    allow_methods=["*"],      # 모든 HTTP 메서드 허용
    allow_headers=["*"],      # 모든 헤더 허용
)

# OpenAI 클라이언트: API 키가 있을 때만 생성한다. (키가 없으면 None → Fallback 동작)
client = OpenAI() if os.getenv("OPENAI_API_KEY") else None

# 맛집 검색에 쓰는 카카오 / 네이버 API 키와 주소
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
KAKAO_LOCAL_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
NAVER_LOCAL_SEARCH_URL = "https://openapi.naver.com/v1/search/local.json"

# 날씨 조회를 위한 주요 야구장 좌표(위도/경도). 도구 3(날씨)에서 사용한다.
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


# ==============================================================================
# 3. 요청 데이터 모델 (Pydantic)
#    - 프론트엔드가 보내는 JSON의 형식을 미리 정의해 자동 검증한다.
# ==============================================================================
class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]  # 누가 한 말인지 (사용자 / 챗봇)
    content: str                        # 실제 대화 내용


class ChatRequest(BaseModel):
    message: str                        # 사용자의 이번 질문
    history: list[ChatTurn] = []        # 이전 대화 기록(맥락 유지용)


# ==============================================================================
# 4. 데이터베이스 (SQLite) — 일정 저장소
# ==============================================================================

# DB 연결: row_factory를 설정해 결과를 row["game_date"]처럼 이름으로 읽게 한다.
def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)  # data 폴더가 없으면 생성
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# 경기 정보를 담을 테이블을 만든다. gmkey(경기 고유키)를 기본키로 써서 중복 저장을 막는다.
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
        # 날짜로 자주 조회하므로 인덱스를 만들어 검색 속도를 높인다.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_games_date ON games(game_date)")


# LG 공식 사이트의 "월별 경기" API를 호출한다. (외부 데이터를 가져오는 단계)
def fetch_month(year: int, month: int) -> list[dict[str, Any]]:
    data = urllib.parse.urlencode({"year": year, "month": month}).encode("utf-8")
    request = urllib.request.Request(
        LG_API_URL,
        data=data,
        headers={"User-Agent": "Mozilla/5.0"},  # 일반 브라우저처럼 보이게 헤더 설정
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != "OK":            # 정상 응답이 아니면 오류 발생
        raise RuntimeError(payload.get("message", "LG 트윈스 일정 조회 실패"))
    return payload.get("data", {}).get("data", [])


# API 원본 데이터를 "LG 기준"으로 깔끔하게 정리한다.
# (홈/원정, 상대팀, 점수, 승패, 경기 상태 등을 우리 앱이 쓰기 좋은 형태로 변환)
def normalize_game(game: dict[str, Any]) -> dict[str, Any]:
    home_key = game.get("homeKey")
    visit_key = game.get("visitKey")
    is_home = home_key == "LG"                 # LG가 홈팀인지 여부
    opponent = game.get("visitName") if is_home else game.get("homeName")
    home_score = int(game.get("hscore") or 0)
    visit_score = int(game.get("vscore") or 0)
    lg_score = home_score if is_home else visit_score        # LG 득점
    opponent_score = visit_score if is_home else home_score  # 상대 득점
    cancel_flag = game.get("cancelFlag")
    end_flag = game.get("endFlag")
    result = ""

    # 경기 상태(취소/종료/예정)를 구분하고, 종료 경기는 승·패·무를 계산한다.
    if cancel_flag == "1":
        status = "경기취소"
    elif end_flag == "1":
        status = "경기종료"
        result = "승" if lg_score > opponent_score else "패" if lg_score < opponent_score else "무"
    else:
        status = "경기전"

    # "20260624" 형태의 날짜를 "2026-06-24"로 변환한다.
    gamedate = str(game.get("gamedate", ""))
    return {
        # DB 컬럼명과 동일한 key로 반환 → INSERT 문에 그대로 바인딩 가능
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


# 한 해(1~12월) 전체를 호출해 LG 경기만 골라 DB에 저장한다.
# INSERT OR REPLACE → 이미 있는 경기는 최신 정보로 갱신, 일부 월 실패해도 계속 진행.
def update_schedule_database(year: int | None = None) -> int:
    create_table()
    saved_count = 0
    target_year = year or datetime.now(KST).year
    for month in range(1, 13):
        try:
            games = [
                normalize_game(game)
                for game in fetch_month(target_year, month)
                # LG가 홈 또는 원정으로 참여한 경기만 필터링
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
            # 특정 월 조회가 실패해도 전체가 멈추지 않도록 건너뛴다.
            continue
    return saved_count


# 사용자의 자연어("오늘", "내일", "6월 24일")에서 날짜(YYYY-MM-DD)를 뽑아낸다.
def parse_date(text: str) -> str | None:
    today = datetime.now(KST).date()
    compact = re.sub(r"\s+", "", text).lower()  # 공백 제거 + 소문자화
    # 1) 상대 날짜 표현 처리
    relative = {"오늘": 0, "내일": 1, "모레": 2, "어제": -1}
    for word, delta in relative.items():
        if word in compact:
            return (today + timedelta(days=delta)).isoformat()
    if "today" in compact:
        return today.isoformat()
    if "tomorrow" in compact:
        return (today + timedelta(days=1)).isoformat()

    # 2) "2026-06-24", "2026년 6월 24일" 같은 연-월-일 형식
    match = re.search(r"(20\d{2})[-./년]*(\d{1,2})[-./월]*(\d{1,2})", compact)
    if match:
        year, month, day = map(int, match.groups())
        return date(year, month, day).isoformat()

    # 3) "6/24", "6월 24일" 처럼 연도가 없으면 올해로 가정
    match = re.search(r"(\d{1,2})[-./월](\d{1,2})", compact)
    if match:
        month, day = map(int, match.groups())
        return date(today.year, month, day).isoformat()
    return None


# 달력 화면 등에서 쓸, DB에 저장된 올해 경기 날짜 목록을 반환한다.
# DB가 비어 있으면 먼저 갱신한 뒤 다시 조회한다(자동 채우기).
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


# DB 한 행을 챗봇/프론트가 쓰기 쉬운 dict로 바꾸고, 홈/원정 표시를 덧붙인다.
def row_to_game(row: sqlite3.Row) -> dict[str, Any]:
    game = dict(row)
    game["home_or_away"] = "홈" if game.get("is_home") else "원정"
    return game


# DB 한 행을 사람이 읽기 좋은 경기 설명 문장으로 변환한다.
def format_game(row: sqlite3.Row) -> str:
    home_or_away = "홈" if row["is_home"] else "원정"
    lines = [
        f"{row['game_date']}({row['weekday']}) {row['game_time']} LG 트윈스 vs {row['opponent']}",
        f"장소: {row['stadium']} / 구분: {home_or_away} {row['game_type']} / 상태: {row['status']}",
    ]
    if row["status"] == "경기종료":  # 끝난 경기는 점수와 결과를 함께 표시
        lines.append(f"결과: LG {row['lg_score']} : {row['opponent_score']} {row['opponent']} ({row['result']})")
    return "\n".join(lines)


# ==============================================================================
# ★ TOOL 1. 경기 일정 조회
#   - 날짜 / 이번 주 / 주말 등 조건에 맞는 LG 경기를 DB에서 찾아 돌려준다.
#   - 결과가 없으면 해당 연도 일정을 갱신한 뒤 한 번 더 조회한다.
# ==============================================================================
def get_lg_twins_schedule(query: str = "", game_date: str | None = None) -> dict[str, Any]:
    create_table()
    target_date = game_date or parse_date(query)
    today = datetime.now(KST).date()
    compact_query = re.sub(r"\s+", "", query)

    # 질문 유형에 따라 조회 기간(start ~ end)을 정한다.
    if "주말" in compact_query:
        start = today + timedelta(days=(5 - today.weekday()) % 7)  # 다가오는 토요일
        end = start + timedelta(days=1)                            # 일요일까지
    elif "이번주" in compact_query:
        start = today - timedelta(days=today.weekday())            # 이번 주 월요일
        end = start + timedelta(days=6)                            # 일요일까지
    elif target_date:
        start = end = date.fromisoformat(target_date)              # 특정 하루
    else:
        start = today                                              # 기본: 오늘부터
        end = today + timedelta(days=14)                           # 2주간

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

    # 조회 결과가 없으면 그 해 일정을 새로 받아온 뒤 다시 조회한다.
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
        # 모델이 곧바로 활용할 수 있도록 요약 문장도 함께 만들어 둔다.
        "summary": "\n\n".join(format_game(row) for row in rows) if rows else "해당 기간에는 등록된 LG 트윈스 경기가 없습니다.",
    }


# ==============================================================================
# ★ TOOL 2. 예매 / 좌석 안내
#   - 질문에 '예매' 관련 단어가 있으면 예매 절차를,
#     '좌석' 관련 단어가 있으면 좌석 선택 팁을 안내한다.
# ==============================================================================

# 질문 의도를 'booking'(예매) / 'seat'(좌석) / 'booking_and_seat'(둘 다)로 분류한다.
def get_booking_intent(topic: str) -> str:
    compact = re.sub(r"\s+", "", topic)
    has_booking = any(word in compact for word in ["예매", "티켓", "인터파크", "결제", "입장권", "예약"])
    has_seat = any(word in compact for word in ["좌석", "자리", "내야", "외야", "응원석", "어디서", "구역", "시야"])

    if has_booking and has_seat:
        return "booking_and_seat"
    if has_seat:
        return "seat"
    return "booking"


# 예매 절차와 좌석 팁을 묶어 반환한다. (의도에 따라 답변 측에서 골라 쓴다)
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


# 경기장 이름으로 좌표를 찾는다. 못 찾으면 기본값(잠실야구장)을 쓴다.
def stadium_coord(stadium: str) -> dict[str, float]:
    for key, coord in STADIUM_COORDS.items():
        if key in stadium:
            return coord
    return STADIUM_COORDS["잠실야구장"]


# ==============================================================================
# ★ TOOL 3. 날씨 기반 복장 추천
#   - 선택한 경기장의 Open-Meteo 날씨 예보를 받아와
#     기온·강수확률에 맞는 옷차림과 준비물을 추천한다.
# ==============================================================================

# 평균기온과 강수확률만으로 옷차림·준비물을 정하는 규칙 기반 함수(외부 호출 없음).
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
    if rain >= 50:                      # 비 올 확률이 높으면 우비·방수가방 추가
        extras.extend(["우비", "방수 가방"])
    if avg < 18:                        # 쌀쌀하면 담요 추가
        extras.append("작은 담요")
    return f"평균 {avg}도 기준으로 {outfit}을 추천해요. 준비물은 {', '.join(extras)}가 좋아요."


# 날짜 → 해당 경기 찾기 → 경기장 좌표 → 날씨 API 호출 → 복장 추천까지 한 번에 처리.
def recommend_outfit_by_weather(game_date: str | None = None, query: str = "") -> dict[str, Any]:
    target_date = game_date or parse_date(query)
    if not target_date:
        return {"tool_name": "recommend_outfit_by_weather", "error": "복장 추천을 받을 경기 날짜를 먼저 알려 주세요."}

    # 그 날짜의 경기를 찾는다(경기가 있어야 경기장 좌표를 알 수 있음).
    schedule = get_lg_twins_schedule(game_date=target_date)
    if not schedule["games"]:
        return {"tool_name": "recommend_outfit_by_weather", "error": f"{target_date}에는 등록된 LG 트윈스 경기가 없습니다."}

    game = schedule["games"][0]
    coord = stadium_coord(game["stadium"])
    # Open-Meteo: 무료 날씨 API. 일별 최고/최저기온, 강수확률·강수량을 요청한다.
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={coord['lat']}&longitude={coord['lon']}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum"
        "&timezone=Asia%2FSeoul"
    )
    with urllib.request.urlopen(url, timeout=10) as response:
        daily = json.loads(response.read().decode("utf-8"))["daily"]
    # 예보는 보통 7일 이내만 제공되므로, 해당 날짜가 없으면 안내 메시지를 준다.
    if target_date not in daily["time"]:
        return {
            "tool_name": "recommend_outfit_by_weather",
            "game": game,
            "error": "날씨 예보는 오늘부터 약 7일 이내 경기만 조회할 수 있어요.",
        }

    index = daily["time"].index(target_date)  # 해당 날짜의 위치(인덱스)
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


# ==============================================================================
# ★ TOOL 4. 잠실 음식점 추천
#   - 경기장 "주변(outside)" 맛집은 카카오/네이버 로컬 검색 API로 실제 업체만 추천한다.
#     (LLM이 가게 이름을 지어내지 못하게 하는 것이 핵심)
#   - 경기장 "내부(inside)" 매점은 지도 API에 잘 안 잡혀, 직접 확인한 고정 목록을 쓴다.
# ==============================================================================

# 카카오 로컬(키워드) 검색: 좌표 기준 가까운 순으로 업체를 가져온다.
def search_kakao_local(query: str, lat: float, lon: float, radius: int, limit: int = 5) -> list[dict[str, Any]]:
    if not KAKAO_REST_API_KEY:   # 키가 없으면 빈 목록 반환
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
    except Exception:            # 검색 실패 시에도 앱이 죽지 않도록 빈 목록 반환
        return []
    return payload.get("documents", [])


# 네이버 로컬 검색: 카카오 검색이 실패했을 때의 대체 수단으로 사용한다.
def search_naver_local(query: str, limit: int = 5) -> list[dict[str, Any]]:
    if not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET):
        return []
    params = urllib.parse.urlencode({"query": query, "display": min(limit, 5), "sort": "comment"})
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


# 여러 검색어를 차례로 시도하고, 결과가 나오는 첫 검색어의 결과를 사용한다.
def search_naver_local_multi(queries: list[str], limit: int = 5) -> list[dict[str, Any]]:
    for query in queries:
        items = search_naver_local(query, limit=limit)
        if items:
            return items
    return []


# 음식점이 아닌 시설(구내식당, 관리사무소 등)을 걸러내기 위한 키워드 목록.
NON_RESTAURANT_KEYWORDS = ["구내식당", "사업소", "관리사무소", "복지시설", "편의시설", "자전거도로", "휴게소"]


# 이름/분류에 위 키워드가 들어가면 "음식점이 아님"으로 판단한다.
def is_non_restaurant(name: str, category: str) -> bool:
    text = f"{name} {category}"
    return any(keyword in text for keyword in NON_RESTAURANT_KEYWORDS)


# 카카오 검색 결과 한 건을 챗봇이 쓰기 좋은 형태(이름/메뉴/위치/추천이유)로 정리한다.
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


# 네이버 검색 결과 한 건을 같은 형태로 정리한다. (<b> 같은 HTML 태그 제거 포함)
def format_naver_place(place: dict[str, Any]) -> dict[str, str]:
    name = re.sub(r"</?b>", "", place.get("title", "이름 확인 필요"))
    category = place.get("category") or "음식점"
    address = place.get("roadAddress") or place.get("address") or "주소 확인 필요"
    reason = f"네이버 검색 기준 {category} 매장이에요."
    if place.get("telephone"):
        reason += f" 문의: {place['telephone']}"
    return {"name": name, "menu": category, "location": address, "reason": reason}


# [발표 포인트] 야구장 내부 매점은 지도 API에 음식점으로 등록되지 않는 경우가 많다.
# 그래서 검색에 의존하지 않고, 직접 확인한 매장만 고정 목록으로 관리해 항상 정확하게 안내한다.
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


# 내부 매점 추천: 사용자가 원하는 조건(식사/간식/인기)에 맞는 고정 목록을 골라 반환한다.
def recommend_inside_stadium_food(condition: str) -> dict[str, Any]:
    matches = [item for item in INSIDE_STADIUM_FOOD if item["condition"] == condition] or INSIDE_STADIUM_FOOD
    restaurants = [{k: v for k, v in item.items() if k != "condition"} for item in matches]
    return {
        "tool_name": "recommend_jamsil_food",
        "source": "curated_list",   # 데이터 출처: 직접 만든 고정 목록
        "place": "inside",
        "condition": condition,
        "cuisine": None,
        "restaurants": restaurants,
        "notice": "매장 입점 여부와 메뉴는 변경될 수 있으니 방문 전 확인해 주세요.",
    }


# 실제 검색을 수행하는 함수.
#  - 내부(inside): 고정 목록 사용
#  - 외부(outside): 카카오 먼저 → 실패 시 네이버 → 둘 다 없으면 결과 없음
def search_jamsil_food(place: str, condition: str, cuisine: str | None = None) -> dict[str, Any]:
    if place == "inside":
        return recommend_inside_stadium_food(condition)

    coord = STADIUM_COORDS["잠실야구장"]
    cuisine_label = f"{cuisine} " if cuisine and cuisine != "기타" else ""
    kakao_query = f"잠실 {cuisine_label}맛집".strip()
    naver_queries = [   # 네이버는 여러 검색어를 순서대로 시도
        f"잠실야구장 근처 {cuisine_label}맛집".strip(),
        f"잠실새내 {cuisine_label}맛집".strip(),
        f"잠실 {cuisine_label}맛집".strip(),
    ]
    radius = 1500  # 검색 반경 1.5km

    # 1차: 카카오 검색 + 음식점이 아닌 곳 필터링
    documents = search_kakao_local(kakao_query, coord["lat"], coord["lon"], radius=radius, limit=15)
    documents = [
        doc for doc in documents
        if not is_non_restaurant(doc.get("place_name", ""), doc.get("category_name", ""))
    ]
    if documents:
        restaurants = [format_kakao_place(doc) for doc in documents[:5]]
        source = "kakao_local"
    else:
        # 2차: 카카오 결과가 없으면 네이버로 재시도
        items = search_naver_local_multi(naver_queries, limit=15)
        items = [
            item for item in items
            if not is_non_restaurant(item.get("title", ""), item.get("category", ""))
        ]
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


# 음식 종류(한식/일식/양식/중식)를 알아내기 위한 키워드 사전.
CUISINE_KEYWORDS = {
    "한식": ["한식", "한정식", "국밥", "찌개", "백반", "고기", "삼겹살"],
    "일식": ["일식", "초밥", "스시", "라멘", "돈카츠", "우동"],
    "양식": ["양식", "파스타", "피자", "스테이크", "버거"],
    "중식": ["중식", "짜장", "짬뽕", "탕수육", "마라"],
}


# 사용자 질문에서 음식 종류를 추출한다. "아무거나" 등은 '기타'로 처리한다.
def detect_cuisine(query: str) -> str | None:
    compact = re.sub(r"\s+", "", query)
    for cuisine, keywords in CUISINE_KEYWORDS.items():
        if any(word in compact for word in keywords):
            return cuisine
    if any(word in compact for word in ["기타", "상관없", "아무거나"]):
        return "기타"
    return None


# 음식점 추천의 "진입점" 함수.
#  - 장소(내부/외부)와 조건(식사/간식 등)을 질문에서 추론한다.
#  - 외부인데 음식 종류를 모르면, 검색하지 말고 먼저 음식 종류를 물어보게 안내한다.
#  - API 키가 없으면 그 사실을 알려준다. (정보를 지어내지 않기 위함)
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

    # 장소(내부/외부) 자동 판별: '근처/주변/밖' 등이 있으면 외부, 아니면 내부.
    if not selected_place:
        selected_place = "outside" if any(word in compact for word in ["근처", "주변", "밖", "경기전", "경기후"]) else "inside"
    # 조건(타이밍/카테고리) 자동 판별
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

    # 외부 맛집인데 음식 종류를 모르면 → 먼저 종류를 물어보라고 모델에 신호를 준다.
    if selected_place == "outside" and not selected_cuisine:
        return {
            "tool_name": "recommend_jamsil_food",
            "source": "need_cuisine",
            "place": selected_place,
            "condition": condition,
            "cuisine": None,
            "restaurants": [],
            "notice": "한식/일식/양식/중식/기타 중 어떤 음식을 원하시는지 먼저 물어봐 주세요. 사용자가 답하면 그 음식 종류로 이 도구를 다시 호출해야 합니다.",
        }

    # 외부 검색에 필요한 API 키가 하나도 없으면, 키 설정이 필요하다고 안내한다.
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

    # 실제 검색 실행 (검색 중 오류가 나도 사용자에게 안내 메시지로 돌려준다)
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


# ==============================================================================
# 5. 도구 정의(TOOLS) — OpenAI에게 "이런 도구들이 있다"고 알려주는 명세(JSON Schema)
#    - 모델은 이 설명(description)과 파라미터를 보고 어떤 도구를 어떤 인자로 부를지 정한다.
# ==============================================================================
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

# 도구 이름 → 실제 파이썬 함수를 연결하는 표. 모델이 고른 이름으로 함수를 찾아 실행한다.
TOOL_HANDLERS = {
    "get_lg_twins_schedule": get_lg_twins_schedule,
    "guide_lg_twins_booking": guide_lg_twins_booking,
    "recommend_outfit_by_weather": recommend_outfit_by_weather,
    "recommend_jamsil_food": recommend_jamsil_food,
}

# 모델에게 역할·말투·규칙을 알려주는 시스템 프롬프트. {today}에 오늘 날짜가 들어간다.
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


# ==============================================================================
# 6. Fallback(대체) 로직 — OpenAI를 못 쓸 때를 대비한 "안전망"
#    - 키가 없거나 호출이 실패해도, 키워드 규칙으로 도구를 직접 골라 답한다.
# ==============================================================================

# 질문 속 키워드로 어떤 도구를 쓸지 규칙 기반으로 정한다(모델 없이도 동작).
def fallback_tool_for(message: str) -> tuple[str, dict[str, Any]]:
    compact = re.sub(r"\s+", "", message)
    if any(word in compact for word in ["날씨", "기온", "온도", "복장", "옷", "입고"]):
        return "recommend_outfit_by_weather", {"game_date": parse_date(message), "query": message}
    if any(word in compact for word in ["음식", "먹", "맛집", "간식", "치킨", "떡볶이", "핫도그"]):
        return "recommend_jamsil_food", {"place": None, "timing_or_category": None, "cuisine": None, "query": message}
    if any(word in compact for word in ["예매", "티켓", "좌석", "자리", "인터파크"]):
        return "guide_lg_twins_booking", {"topic": message}
    return "get_lg_twins_schedule", {"query": message, "game_date": parse_date(message)}  # 기본: 일정 조회


# 도구 실행 결과(dict)를 모델 없이 사람이 읽을 답변 문장으로 직접 변환한다.
def local_answer(tool_name: str, tool_result: dict[str, Any]) -> str:
    if tool_name == "get_lg_twins_schedule":
        return tool_result["summary"]
    if tool_name == "guide_lg_twins_booking":
        intent = tool_result.get("intent", "booking")
        if intent == "seat":   # 좌석 질문이면 좌석 팁만 안내
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
    # 음식점 추천 결과 정리
    restaurants = tool_result.get("restaurants", [])
    if not restaurants:
        return tool_result.get("notice", "음식점 검색 결과가 없습니다. 잠시 후 다시 시도해 주세요.")
    lines = [
        f"{item['name']} - {item['menu']} ({item['location']})\n추천 이유: {item['reason']}"
        for item in restaurants
    ]
    return "\n\n".join(lines) + f"\n\n{tool_result['notice']}"


# ==============================================================================
# 7. API 엔드포인트 (실제 외부 요청을 받는 통로)
# ==============================================================================

# [GET] /api/calendar-dates : 달력에 표시할 경기 날짜 목록을 돌려준다.
@app.get("/api/calendar-dates")
def calendar_dates(year: int | None = None):
    return {"dates": available_game_dates(year)}


# [POST] /api/chat : 챗봇의 핵심 엔드포인트. 사용자의 메시지를 받아 답변을 만든다.
@app.post("/api/chat")
def chat(request: ChatRequest):
    message = request.message.strip()
    if not message:   # 빈 질문 방어
        return {"answer": "질문을 입력해 주세요.", "tool": None, "tool_result": None, "link": BOOKING_LINK}

    # ── (A) OpenAI 키가 없으면: Fallback 규칙으로 도구 선택 → 직접 답변 생성 ──
    if client is None:
        tool_name, args = fallback_tool_for(message)
        tool_result = TOOL_HANDLERS[tool_name](**args)
        return {"answer": local_answer(tool_name, tool_result), "tool": tool_name, "tool_result": tool_result, "link": BOOKING_LINK}

    # ── (B) OpenAI 사용: 대화 맥락을 구성한다 ──
    system_prompt = SYSTEM_PROMPT.format(today=datetime.now(KST).date().isoformat())
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for turn in request.history[-12:]:   # 최근 12개 대화만 맥락으로 사용
        messages.append({"role": turn.role, "content": turn.content})
    # 사용자 메시지에 오늘 날짜/시간대를 덧붙여 상대 날짜 해석을 돕는다.
    messages.append({"role": "user", "content": f"{message}\n\n[현재 날짜: {datetime.now(KST).date().isoformat()} / 시간대: KST]"})

    try:
        # 1차 호출: 모델이 "어떤 도구를 부를지" 판단한다.
        first = client.responses.create(
            model=DEFAULT_MODEL,
            input=messages,
            tools=TOOLS,
            tool_choice="auto",      # 도구를 쓸지 말지 모델이 자동 결정
            temperature=0.2,
            max_output_tokens=700,
        )
        # 모델이 호출하기로 한 도구(function_call) 목록을 추린다.
        function_calls = [item for item in first.output if item.type == "function_call"]
        if not function_calls:       # 도구 없이 바로 답한 경우 그 답을 반환
            return {"answer": first.output_text, "tool": None, "tool_result": None, "link": BOOKING_LINK}

        # 모델이 고른 도구들을 실제로 실행하고 그 결과를 모은다.
        tool_outputs = []
        last_tool_name = None
        last_tool_result = None
        for call in function_calls:
            args = json.loads(call.arguments or "{}")    # 모델이 채워준 인자(JSON)
            last_tool_name = call.name
            last_tool_result = TOOL_HANDLERS[call.name](**args)  # 실제 함수 실행
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(last_tool_result, ensure_ascii=False),
                }
            )

        # 2차 호출: 도구 실행 결과를 모델에 다시 넘겨 "최종 한국어 답변"을 만들게 한다.
        final = client.responses.create(
            model=DEFAULT_MODEL,
            previous_response_id=first.id,   # 1차 대화에 이어서 진행
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
        # OpenAI 호출 중 문제가 생기면 Fallback으로 안전하게 답하고 경고를 함께 준다.
        tool_name, args = fallback_tool_for(message)
        tool_result = TOOL_HANDLERS[tool_name](**args)
        return {
            "answer": local_answer(tool_name, tool_result),
            "tool": tool_name,
            "tool_result": tool_result,
            "link": BOOKING_LINK,
            "warning": f"OpenAI 도구 선택 중 문제가 있어 기본 분류로 답했어요: {exc}",
        }


# 프론트엔드(정적 파일)를 "/" 경로에 연결한다. 브라우저로 접속하면 화면이 보인다.
# (※ 이 mount는 위의 API 경로들이 모두 정의된 뒤에 마지막으로 실행되어야 한다.)
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
