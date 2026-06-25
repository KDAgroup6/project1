"""LG 트윈스 경기 일정 챗봇 (발표용 코드)

[프로그램 한 줄 요약]
LG 트윈스 공식 API에서 경기 일정을 받아 SQLite DB에 저장하고,
사용자의 자연어 날짜 질문("내일", "다음주 화요일" 등)을 해석해
해당 경기 정보를 챗봇으로 답해 주는 Gradio 웹앱.

[데이터 흐름 — 발표 4단계]
  1) 수집  fetch_month()       : 공식 API를 월별로 호출해 원본 일정 받기
  2) 가공  normalize_game()    : 사이트 기준 데이터를 'LG 기준'으로 정리(승/패, 홈/원정 등)
  3) 저장  save_games()/DB     : SQLite에 INSERT OR REPLACE 로 중복 없이 저장·갱신
  4) 응답  extract_date() →    : 질문에서 날짜를 뽑아 answer_schedule()로 답변 문장 생성

[발표 때 강조하면 좋은 부분]
  - 자연어 날짜 파싱: extract_date() 와 보조 함수들(상대일·주·요일·숫자날짜 순서대로 검사)
  - Gradio UI: 슬라이더·드롭다운·챗봇이 같은 '선택 날짜'를 공유하도록 이벤트로 연결
"""

from __future__ import annotations              # 미래 기능을 미리 사용하는 설정 / 타입 힌트(자료형 표시)를 더 유연하게

import re                                       # 정규표현식(문자 패턴 찾기) 라이브러리
import sqlite3                                  # SQLite 데이터데이스 사용
from datetime import date, datetime, timedelta  # 시간 관련 기능들(날짜, 날짜와 시간, 시간 차이 계산)
from pathlib import Path                        # 파일/폴더 경로를 다루는 최신 방식
from typing import Any                          # 타입 힌트용 / any는 아무 타입이나 가능
from zoneinfo import ZoneInfo                   # 시간대 처리

import gradio as gr                             # 웹 UI
import requests                                 # API 호출


# 발표 포인트: 이 프로그램은 LG 트윈스 경기 일정을 공식 API에서 가져와
# SQLite DB에 저장하고, 사용자의 날짜 질문에 맞는 경기 정보를 챗봇 형태로 보여준다.
API_URL = "https://www.lgtwins.com/api/game/getGame"
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "lg_twins_schedule.db"
KST = ZoneInfo("Asia/Seoul")
DEFAULT_YEAR = datetime.now(KST).date().year


# 자연어 질문에서 "월요일", "내일" 같은 표현을 실제 날짜 계산에 쓰기 위한 기준값이다.
WEEKDAY_NUMBERS = {
    "월": 0,
    "월요일": 0,
    "화": 1,
    "화요일": 1,
    "수": 2,
    "수요일": 2,
    "목": 3,
    "목요일": 3,
    "금": 4,
    "금요일": 4,
    "토": 5,
    "토요일": 5,
    "일": 6,
    "일요일": 6,
}
RELATIVE_DAYS = {
    "그제": -2,
    "그저께": -2,
    "엊그제": -2,
    "어제": -1,
    "오늘": 0,
    "내일": 1,
    "낼모레": 2,
    "모레": 2,
}


# DB 연결 함수: row_factory를 설정해 조회 결과를 row["game_date"]처럼 읽기 쉽게 만든다.
def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# 경기 일정 저장소를 준비한다.
# gmkey를 기본키로 사용하므로 같은 경기를 다시 저장해도 중복이 생기지 않는다.
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


# LG 트윈스 공식 사이트의 월별 경기 API를 호출한다.
# 발표에서는 "외부 데이터를 가져오는 단계"로 설명하면 된다.
def fetch_month(year: int, month: int) -> list[dict[str, Any]]:
    response = requests.post(
        API_URL,
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


# API 원본 데이터는 사이트 기준 필드명과 팀 기준이 섞여 있으므로,
# 앱에서 쓰기 편하도록 "LG 기준"의 일정 데이터로 정리한다.
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
    game_type = "시범경기" if game.get("gameFlag") == "1" else "정규경기"

    # 경기 취소, 경기 종료, 진행 예정 상태를 구분하고 종료된 경기는 승/패/무를 계산한다.
    result = ""
    if cancel_flag == "1":
        status = "경기취소"
    elif end_flag == "1":
        status = "경기종료"
        if lg_score > opponent_score:
            result = "승"
        elif lg_score < opponent_score:
            result = "패"
        else:
            result = "무"
    else:
        status = "경기전"

    gamedate = str(game.get("gamedate", ""))
    game_date = f"{gamedate[:4]}-{gamedate[4:6]}-{gamedate[6:8]}"

    # DB 컬럼명과 같은 key로 반환해서 INSERT 문에 바로 바인딩할 수 있게 한다.
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
        "dheader": game.get("dheader", "0"),
        "game_type": game_type,
        "status": status,
        "lg_score": lg_score,
        "opponent_score": opponent_score,
        "result": result,
        "raw_home_key": home_key,
        "raw_visit_key": visit_key,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


# API에서 받은 경기 목록 중 LG 경기만 골라 DB에 저장한다.
# INSERT OR REPLACE를 사용해 이미 저장된 경기 정보도 최신 상태로 갱신한다.
def save_games(games: list[dict[str, Any]]) -> int:
    normalized_games = [
        normalize_game(game)
        for game in games
        if game.get("gmkey") and (game.get("homeKey") == "LG" or game.get("visitKey") == "LG")
    ]

    with connect_db() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO games (
                gmkey, game_date, game_time, weekday, stadium,
                home_team, away_team, opponent, is_home, dheader,
                game_type, status, lg_score, opponent_score, result,
                raw_home_key, raw_visit_key, updated_at
            )
            VALUES (
                :gmkey, :game_date, :game_time, :weekday, :stadium,
                :home_team, :away_team, :opponent, :is_home, :dheader,
                :game_type, :status, :lg_score, :opponent_score, :result,
                :raw_home_key, :raw_visit_key, :updated_at
            )
            """,
            normalized_games,
        )

    return len(normalized_games)


# 한 해의 1월부터 12월까지 차례대로 호출해 DB를 최신 일정으로 채운다.
# 일부 월에서 실패하더라도 나머지 월은 계속 저장하고, 실패 목록을 메시지에 포함한다.
def update_database(year: int = DEFAULT_YEAR) -> str:
    create_table()

    saved_count = 0
    failed_months: list[str] = []
    for month in range(1, 13):
        try:
            games = fetch_month(year, month)
            saved_count += save_games(games)
        except Exception as exc:
            failed_months.append(f"{month}월({exc})")

    if failed_months:
        return f"{year}년 일정 {saved_count}건을 저장했습니다. 실패: {', '.join(failed_months)}"
    return f"{year}년 LG 트윈스 일정 {saved_count}건을 DB에 저장했습니다."


# 드롭다운과 슬라이더에 표시할 수 있도록 DB에 존재하는 경기 날짜만 가져온다.
def get_available_dates(year: int = DEFAULT_YEAR) -> list[str]:
    create_table()
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT game_date
            FROM games
            WHERE substr(game_date, 1, 4) = ?
            ORDER BY game_date
            """,
            (str(year),),
        ).fetchall()
    return [row["game_date"] for row in rows]


# 사용자가 특정 날짜를 선택하거나 질문했을 때, 그 날짜의 경기만 조회한다.
def get_games_by_date(game_date: str) -> list[sqlite3.Row]:
    with connect_db() as conn:
        return conn.execute(
            """
            SELECT *
            FROM games
            WHERE game_date = ?
            ORDER BY game_time, gmkey
            """,
            (game_date,),
        ).fetchall() # DB에서 조회한 결과를 전부 가져오는 함수


# "이번 주", "다음 주말"처럼 기간 질문이 들어왔을 때 해당 범위의 경기를 조회한다.
def get_games_in_range(start_date: str, end_date: str) -> list[sqlite3.Row]:
    with connect_db() as conn:
        return conn.execute(
            """
            SELECT *
            FROM games
            WHERE game_date BETWEEN ? AND ?
            ORDER BY game_date, game_time, gmkey
            """,
            (start_date, end_date),
        ).fetchall()


# DB 한 행(row)을 사용자가 읽기 쉬운 경기 설명 문장으로 바꾼다.
def format_game(row: sqlite3.Row) -> str:
    home_or_away = "홈" if row["is_home"] else "원정"
    double_header = ", 더블헤더" if row["dheader"] in ("1", "2") else ""
    base = "\n".join(
        [
            f"시간: {row['game_time']}",
            f"경기장소: {row['stadium']}",
            f"상대팀: {row['opponent']}",
            "",
            f"경기: LG 트윈스 vs {row['opponent']} ({home_or_away}{double_header})",
        ]
    )

    if row["status"] == "경기종료":
        return (
            f"{base}\n"
            f"결과: LG {row['lg_score']} : {row['opponent_score']} {row['opponent']} "
            f"({row['result']})"
        )
    if row["status"] == "경기취소":
        return f"{base}\n상태: 경기취소"
    return f"{base}\n상태: {row['status']}"


# 하루 일정 답변 생성 함수: 날짜 하나를 기준으로 챗봇 응답 문장을 만든다.
def answer_schedule(game_date: str) -> str:
    if not game_date:
        return "날짜를 먼저 선택해 주세요."

    games = get_games_by_date(game_date)
    if not games:
        return f"{game_date}에는 등록된 LG 트윈스 경기가 없습니다."

    weekday = games[0]["weekday"]
    lines = [f"{game_date}({weekday}) LG 트윈스 경기 일정입니다."]
    for index, game in enumerate(games, start=1):
        lines.append(f"\n[{index}경기]\n{format_game(game)}")
    return "\n".join(lines)


# 기간 일정 답변 생성 함수: 여러 날짜의 경기를 날짜별로 묶어서 보여준다.
def answer_schedule_range(start_date: str, end_date: str, title: str) -> str:
    if not start_date or not end_date:
        return "기간을 먼저 확인할 수 없어요."

    games = get_games_in_range(start_date, end_date)
    if not games:
        return f"{title}({start_date} ~ {end_date})에는 등록된 LG 트윈스 경기가 없습니다."

    lines = [f"{title}({start_date} ~ {end_date}) LG 트윈스 경기 일정입니다."]
    current_date = None
    count = 0

    for game in games:
        if game["game_date"] != current_date:
            current_date = game["game_date"]
            count = 0
            lines.append(f"\n{current_date}({game['weekday']})")
        count += 1
        lines.append(f"[{count}경기]\n{format_game(game)}")

    return "\n".join(lines)


# 모든 날짜 계산은 한국 시간 기준으로 맞춘다.
def today_kst() -> date:
    return datetime.now(KST).date()


# 잘못된 날짜(예: 2월 30일)가 들어오면 None을 반환해 안전하게 처리한다.
def make_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


# "오늘", "내일", "어제" 같은 상대 날짜 표현을 실제 날짜로 변환한다.
def extract_relative_day(text: str) -> str | None:
    for word, delta in RELATIVE_DAYS.items():
        if word in text:
            return (today_kst() + timedelta(days=delta)).isoformat() # 시간을 국제표준형식 문자열로 변환해주는 함수
    return None


# "이번 주", "다음 주", "지난 주" 표현을 몇 주 차이인지 숫자로 바꾼다.
def week_start_offset(text: str) -> int | None:
    compact_text = re.sub(r"\s+", "", text)
    if "다다음주" in compact_text:
        return 2
    if "다음주" in compact_text:
        return 1
    if "이번주" in compact_text:
        return 0
    if "저번주" in compact_text or "지난주" in compact_text:
        return -1
    return None


# 주 단위 질문을 시작일과 종료일로 변환한다.
# 예: "다음 주 일정" -> 다음 주 월요일부터 일요일까지의 날짜 범위.
def extract_week_range(text: str) -> tuple[str, str, str] | None:
    compact_text = re.sub(r"\s+", "", text)
    if re.search(r"(월요일|화요일|수요일|목요일|금요일|토요일|일요일)", compact_text):
        return None

    offset = week_start_offset(compact_text)
    if offset is None:
        return None

    monday = today_kst() - timedelta(days=today_kst().weekday())
    start = monday + timedelta(days=offset * 7)
    end = start + timedelta(days=6)

    if "주말" in compact_text:
        start = start + timedelta(days=5)
        end = start + timedelta(days=1)
        title = {
            2: "다다음주말",
            1: "다음주말",
            0: "이번주말",
            -1: "저번주말",
        }[offset]
        return start.isoformat(), end.isoformat(), title

    if "일정" in compact_text or "경기" in compact_text or "모두" in compact_text:
        title = {
            2: "다다음주",
            1: "다음주",
            0: "이번주",
            -1: "저번주",
        }[offset]
        return start.isoformat(), end.isoformat(), title

    return None


# "이번 주말", "다음 주말"처럼 주말을 묻는 질문은 토요일 날짜를 대표 날짜로 잡는다.
def extract_weekend_date(text: str) -> str | None:
    compact_text = re.sub(r"\s+", "", text)
    weekend_offsets = {
        "다다음주말": 2,
        "다음주말": 1,
        "이번주말": 0,
        "저번주말": -1,
        "지난주말": -1,
        "주말": 0,
    }

    for word, week_offset in weekend_offsets.items():
        if word in compact_text:
            monday = today_kst() - timedelta(days=today_kst().weekday())
            saturday = monday + timedelta(days=5 + week_offset * 7)
            return saturday.isoformat()

    return None


# "다음 주 화요일", "금요일"처럼 요일이 포함된 질문을 실제 날짜로 바꾼다.
def extract_weekday_date(text: str) -> str | None:
    compact_text = re.sub(r"\s+", "", text)
    weekday_pattern = "월요일|화요일|수요일|목요일|금요일|토요일|일요일|월|화|수|목|금|토|일"
    week_offsets = {
        "다다음주": 2,
        "다음주": 1,
        "담주": 1,
        "이번주": 0,
        "이번": 0,
        "지난주": -1,
        "저번주": -1,
        "저저번주": -2,
        "지지난주": -2
    }

    for prefix, week_offset in week_offsets.items():
        match = re.search(prefix + f"({weekday_pattern})", compact_text)
        if match:
            weekday = WEEKDAY_NUMBERS[match.group(1)]
            monday = today_kst() - timedelta(days=today_kst().weekday())
            return (monday + timedelta(days=week_offset * 7 + weekday)).isoformat()

    match = re.search(r"(월요일|화요일|수요일|목요일|금요일|토요일|일요일)", compact_text)
    if match:
        weekday = WEEKDAY_NUMBERS[match.group(1)]
        days_ahead = (weekday - today_kst().weekday()) % 7
        return (today_kst() + timedelta(days=days_ahead)).isoformat()

    return None


# ★발표 포인트(핵심): 챗봇 질문에서 날짜를 추출하는 가장 중요한 함수.
# "오늘/내일" → "이번주말" → "다음주 화요일" → "2026-06-24" → "6/24" 순으로
# 더 구체적인 표현부터 차례대로 검사해, 가장 먼저 매칭되는 날짜를 돌려준다.
def extract_date(text: str) -> str | None:
    text = text.strip()

    relative_date = extract_relative_day(text)
    if relative_date:
        return relative_date

    week_range = extract_week_range(text)
    if week_range:
        return week_range[0]

    weekend_date = extract_weekend_date(text)
    if weekend_date:
        return weekend_date

    weekday_date = extract_weekday_date(text)
    if weekday_date:
        return weekday_date

    match = re.search(r"(20\d{2})[-./년\s]*(\d{1,2})[-./월\s]*(\d{1,2})", text)
    if match:
        year, month, day = map(int, match.groups())
        return make_date(year, month, day)

    match = re.search(r"(\d{1,2})[-./월\s]*(\d{1,2})", text)
    if match:
        month, day = map(int, match.groups())
        return make_date(today_kst().year, month, day)

    return None


# 기간형 질문인지 확인한다. 현재는 주 단위 질문을 기간 질문으로 처리한다.
def extract_range_query(text: str) -> tuple[str, str, str] | None:
    compact_text = re.sub(r"\s+", "", text)
    return extract_week_range(compact_text)


# 슬라이더 값으로 날짜를 선택했을 때 챗봇 답변과 선택 날짜를 함께 갱신한다.
def select_date_by_dial(index: int, dates: list[str]) -> tuple[str, str, list[dict[str, str]]]:
    if not dates:
        message = "DB에 저장된 일정이 없습니다. 먼저 'DB 새로 만들기'를 눌러 주세요."
        return "", message, [{"role": "assistant", "content": message}]

    safe_index = max(0, min(int(index), len(dates) - 1))
    selected_date = dates[safe_index]
    answer = answer_schedule(selected_date)
    return selected_date, selected_date, [{"role": "assistant", "content": answer}]


# 사용자의 채팅 입력을 해석해 단일 날짜 질문인지 기간 질문인지 나눈 뒤 답변을 만든다.
def ask_chatbot(message: str, selected_date: str, history: list[dict[str, str]]) -> list[dict[str, str]]:
    history = history or []
    message = (message or "").strip()
    range_query = extract_range_query(message)

    # 기간 질문이면 범위 조회를 사용하고, 아니면 추출된 날짜나 현재 선택 날짜를 사용한다.
    if range_query:
        start_date, end_date, title = range_query
        answer = answer_schedule_range(start_date, end_date, title)
        target_date = start_date
    else:
        target_date = extract_date(message) or selected_date
        answer = answer_schedule(target_date)

    if message:
        history.append({"role": "user", "content": message})
    else:
        history.append({"role": "user", "content": f"{target_date} 일정 알려줘"})
    history.append({"role": "assistant", "content": answer})
    return history


# "DB 새로 만들기" 버튼을 눌렀을 때 실행되는 함수다.
# API 재호출, DB 저장, 날짜 목록 갱신, 첫 답변 생성까지 한 번에 처리한다.
def refresh_db(year: int) -> tuple[gr.Dropdown, gr.Slider, str, str, list[dict[str, str]]]:
    year = int(year or DEFAULT_YEAR)
    result_message = update_database(year)
    dates = get_available_dates(year)

    if not dates:
        chatbot_message = f"{result_message}\n선택할 수 있는 날짜가 없습니다."
        return (
            gr.update(choices=[], value=None),
            gr.update(minimum=0, maximum=0, value=0),
            "",
            chatbot_message,
            [{"role": "assistant", "content": chatbot_message}],
        )

    first_date = dates[0]
    answer = answer_schedule(first_date)
    return (
        gr.update(choices=dates, value=first_date),
        gr.update(minimum=0, maximum=len(dates) - 1, value=0),
        first_date,
        result_message,
        [{"role": "assistant", "content": answer}],
    )


# 드롭다운으로 날짜를 바꾸면 슬라이더 위치와 챗봇 답변도 같은 날짜로 맞춘다.
def select_from_dropdown(selected_date: str, dates: list[str]) -> tuple[int, str, list[dict[str, str]]]:
    if not selected_date:
        return 0, "날짜를 선택해 주세요.", []

    index = dates.index(selected_date) if selected_date in dates else 0
    answer = answer_schedule(selected_date)
    return index, selected_date, [{"role": "assistant", "content": answer}]


# 앱이 처음 실행될 때 DB를 준비하고, 기본 연도의 일정을 미리 불러온다.
create_table()
initial_status = update_database(DEFAULT_YEAR)
initial_dates = get_available_dates(DEFAULT_YEAR)
initial_date = initial_dates[0] if initial_dates else ""
initial_chat = [{"role": "assistant", "content": answer_schedule(initial_date)}] if initial_date else []


# ★발표 포인트(화면): Gradio Blocks로 UI를 구성한다.
# 위쪽 = DB 갱신/연도·날짜 선택, 아래쪽 = 챗봇 질문·답변.
# 슬라이더/드롭다운/챗봇이 아래 .click()·.change()·.submit() 이벤트로 서로 연결되어,
# 어느 쪽으로 날짜를 바꿔도 나머지가 같은 날짜로 동기화되는 점을 보여 주면 좋다.
with gr.Blocks(title="LG 트윈스 경기 일정 챗봇") as demo:
    gr.Markdown("# LG 트윈스 경기 일정 챗봇")
    gr.Markdown("공식 홈페이지 일정 API를 가져와 SQLite DB로 저장한 뒤, 날짜를 선택하면 해당 경기 일정을 알려줍니다.")

    dates_state = gr.State(initial_dates)

    with gr.Row():
        year_input = gr.Number(value=DEFAULT_YEAR, precision=0, label="조회 연도")
        refresh_button = gr.Button("DB 새로 만들기", variant="primary")

    status_box = gr.Textbox(value=initial_status, label="DB 상태", interactive=False)

    with gr.Row():
        date_dial = gr.Slider(
            minimum=0,
            maximum=max(len(initial_dates) - 1, 0),
            value=0,
            step=1,
            label="날짜 다이얼",
        )
        date_dropdown = gr.Dropdown(
            choices=initial_dates,
            value=initial_date or None,
            label="날짜 선택",
        )

    selected_date_box = gr.Textbox(value=initial_date, label="선택된 날짜", interactive=False)
    chatbot = gr.Chatbot(value=initial_chat, label="챗봇")
    question = gr.Textbox(
        placeholder="예: 2026-06-24 일정 알려줘 / 7월 3일 경기 있어?",
        label="챗봇에게 물어보기",
    )
    ask_button = gr.Button("물어보기")

    refresh_button.click(
        refresh_db,
        inputs=year_input,
        outputs=[date_dropdown, date_dial, selected_date_box, status_box, chatbot],
    ).then(
        # DB 갱신 후에는 Gradio 상태값(dates_state)도 최신 날짜 목록으로 바꾼다.
        lambda year: get_available_dates(int(year or DEFAULT_YEAR)),
        inputs=year_input,
        outputs=dates_state,
    )

    # 슬라이더와 드롭다운은 같은 날짜 선택 기능을 공유하므로 서로 값을 맞춰준다.
    date_dial.change(
        select_date_by_dial,
        inputs=[date_dial, dates_state],
        outputs=[date_dropdown, selected_date_box, chatbot],
    )

    date_dropdown.change(
        select_from_dropdown,
        inputs=[date_dropdown, dates_state],
        outputs=[date_dial, selected_date_box, chatbot],
    )

    # 엔터로 질문하거나 버튼을 눌러도 같은 챗봇 처리 함수가 실행된다.
    question.submit(
        ask_chatbot,
        inputs=[question, selected_date_box, chatbot],
        outputs=chatbot,
    )
    ask_button.click(
        ask_chatbot,
        inputs=[question, selected_date_box, chatbot],
        outputs=chatbot,
    )


# 파일을 직접 실행했을 때만 웹 앱 서버를 시작한다.
if __name__ == "__main__":
    demo.launch()
