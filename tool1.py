from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import gradio as gr
import requests


API_URL = "https://www.lgtwins.com/api/game/getGame"
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "lg_twins_schedule.db"
KST = ZoneInfo("Asia/Seoul")
DEFAULT_YEAR = datetime.now(KST).date().year
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
    "어제": -1,
    "오늘": 0,
    "내일": 1,
    "모레": 2,
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
        ).fetchall()


def format_game(row: sqlite3.Row) -> str:
    home_or_away = "홈" if row["is_home"] else "원정"
    double_header = ", 더블헤더" if row["dheader"] in ("1", "2") else ""
    base = "\n".join(
        [
            f"시간: {row['game_time']}",
            f"경기장소: {row['stadium']}",
            f"상대팀: {row['opponent']}",
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


def today_kst() -> date:
    return datetime.now(KST).date()


def make_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def extract_relative_day(text: str) -> str | None:
    for word, delta in RELATIVE_DAYS.items():
        if word in text:
            return (today_kst() + timedelta(days=delta)).isoformat()
    return None


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


def extract_date(text: str) -> str | None:
    text = text.strip()

    relative_date = extract_relative_day(text)
    if relative_date:
        return relative_date

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


def select_date_by_dial(index: int, dates: list[str]) -> tuple[str, str, list[dict[str, str]]]:
    if not dates:
        message = "DB에 저장된 일정이 없습니다. 먼저 'DB 새로 만들기'를 눌러 주세요."
        return "", message, [{"role": "assistant", "content": message}]

    safe_index = max(0, min(int(index), len(dates) - 1))
    selected_date = dates[safe_index]
    answer = answer_schedule(selected_date)
    return selected_date, selected_date, [{"role": "assistant", "content": answer}]


def ask_chatbot(message: str, selected_date: str, history: list[dict[str, str]]) -> list[dict[str, str]]:
    history = history or []
    message = (message or "").strip()
    target_date = extract_date(message) or selected_date
    answer = answer_schedule(target_date)

    if message:
        history.append({"role": "user", "content": message})
    else:
        history.append({"role": "user", "content": f"{target_date} 일정 알려줘"})
    history.append({"role": "assistant", "content": answer})
    return history


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


def select_from_dropdown(selected_date: str, dates: list[str]) -> tuple[int, str, list[dict[str, str]]]:
    if not selected_date:
        return 0, "날짜를 선택해 주세요.", []

    index = dates.index(selected_date) if selected_date in dates else 0
    answer = answer_schedule(selected_date)
    return index, selected_date, [{"role": "assistant", "content": answer}]


create_table()
initial_status = update_database(DEFAULT_YEAR)
initial_dates = get_available_dates(DEFAULT_YEAR)
initial_date = initial_dates[0] if initial_dates else ""
initial_chat = [{"role": "assistant", "content": answer_schedule(initial_date)}] if initial_date else []


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
        lambda year: get_available_dates(int(year or DEFAULT_YEAR)),
        inputs=year_input,
        outputs=dates_state,
    )

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


if __name__ == "__main__":
    demo.launch()
