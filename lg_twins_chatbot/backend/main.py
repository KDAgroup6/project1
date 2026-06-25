from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

try:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
    from langgraph.graph import START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode, tools_condition
except ImportError:
    AIMessage = HumanMessage = SystemMessage = None
    ChatOpenAI = None
    START = MessagesState = StateGraph = None
    ToolNode = tools_condition = None


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
DB_PATH = BASE_DIR / "lg_twins_schedule.db"
BOOKING_LINK = "https://ticket.interpark.com"
KST = ZoneInfo("Asia/Seoul")

FOOD_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "restaurants": {
            "type": "array",
            "minItems": 5,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "menu": {"type": "string"},
                    "location": {"type": "string"},
                    "reason": {"type": "string"},
                    "source_title": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["name", "menu", "location", "reason", "source_title", "source_url"],
                "additionalProperties": False,
            },
        },
        "notice": {"type": "string"},
    },
    "required": ["restaurants", "notice"],
    "additionalProperties": False,
}

load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / "backend" / ".env", override=True)

app = FastAPI(title="LG Twins Game Assistant")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class BookingQuestion(BaseModel):
    message: str
    history: list[ChatTurn] = []


class Visual(BaseModel):
    type: Literal["none", "seat_zone", "booking_steps", "schedule", "food", "weather"]
    zone: Literal["infield", "outfield", "cheer"] | None = None


class BookingAnswer(BaseModel):
    answer: str
    link: str = BOOKING_LINK
    visual: Visual = Visual(type="none", zone=None)


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def today_kst() -> date:
    return datetime.now(KST).date()


def add(a: int, b: int) -> int:
    """두 정수 a와 b를 더합니다. 수업 예제와 같은 계산 도구입니다."""
    return a + b


def multiply(a: int, b: int) -> int:
    """두 정수 a와 b를 곱합니다. 수업 예제와 같은 계산 도구입니다."""
    return a * b


def _format_game(row: sqlite3.Row) -> str:
    home_away = "홈경기" if row["is_home"] else "원정경기"
    double_header = ", 더블헤더" if row["dheader"] in ("1", "2") else ""
    score = ""
    if row["status"] == "경기종료":
        score = f", 결과 LG {row['lg_score']}:{row['opponent_score']} {row['opponent']} ({row['result']})"
    return (
        f"{row['game_date']}({row['weekday']}) {row['game_time']} "
        f"{row['stadium']} / vs {row['opponent']} / {home_away}{double_header} / "
        f"{row['game_type']} / {row['status']}{score}"
    )


def _extract_date(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text)
    relative_dates = {
        "그제": today_kst() - timedelta(days=2),
        "어제": today_kst() - timedelta(days=1),
        "오늘": today_kst(),
        "내일": today_kst() + timedelta(days=1),
        "모레": today_kst() + timedelta(days=2),
    }
    for keyword, value in relative_dates.items():
        if keyword in compact:
            return value.isoformat()

    match = re.search(r"(20\d{2})[-./년]?\s*(\d{1,2})[-./월]?\s*(\d{1,2})", text)
    if match:
        year, month, day = map(int, match.groups())
        return date(year, month, day).isoformat()

    match = re.search(r"(\d{1,2})[-./월]\s*(\d{1,2})", text)
    if match:
        month, day = map(int, match.groups())
        return date(today_kst().year, month, day).isoformat()

    return None


def search_lg_schedule(query: str) -> str:
    """LG 트윈스 경기 일정 DB에서 날짜, 상대, 구장, 홈/원정, 경기 상태를 조회합니다."""
    if not DB_PATH.exists():
        return "일정 DB 파일을 찾을 수 없습니다."

    query_date = _extract_date(query)
    with connect_db() as conn:
        if query_date:
            rows = conn.execute(
                """
                SELECT *
                FROM games
                WHERE game_date = ?
                ORDER BY game_time, gmkey
                """,
                (query_date,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM games
                WHERE game_date >= ?
                ORDER BY game_date, game_time, gmkey
                LIMIT 5
                """,
                (today_kst().isoformat(),),
            ).fetchall()

    if not rows:
        target = f"{query_date}에는" if query_date else "가까운 일정 중에는"
        return f"{target} DB에 등록된 LG 트윈스 경기가 없습니다."

    return "\n".join(_format_game(row) for row in rows)


def explain_booking_steps(_: str = "") -> str:
    """LG 트윈스 경기 예매 방법과 예매 전 주의사항을 안내합니다."""
    return (
        "LG 트윈스 홈경기 예매는 보통 인터파크 티켓에서 진행합니다.\n"
        "1. 인터파크 티켓에 접속해 LG 트윈스 또는 원하는 경기 날짜를 검색합니다.\n"
        "2. 경기일, 상대팀, 홈/원정 여부를 확인합니다. 원정 경기는 상대 구단 예매처를 확인해야 할 수 있습니다.\n"
        "3. 좌석 구역과 좌석을 선택한 뒤 결제합니다.\n"
        "4. 결제 후 모바일 티켓 또는 QR 코드로 입장합니다.\n"
        "좌석 잔여 수량, 가격, 예매 오픈 시간은 실시간으로 바뀌므로 최종 결제 전 공식 예매 페이지에서 다시 확인하세요."
    )


def recommend_seat_zone(preferences: str) -> str:
    """예산, 동행 인원, 응원 선호도에 따라 잠실야구장 좌석 구역을 추천합니다."""
    text = preferences.lower()
    if any(word in text for word in ["응원", "신나", "분위기", "치어", "열기", "구장 구역", "색상 영역"]):
        return (
            "cheer: 잠실야구장 기준으로 1루 쪽 LG 응원 구역을 추천합니다. "
            "응원단과 가깝고 chant, 율동, 득점 순간의 분위기를 가장 크게 느낄 수 있습니다."
        )
    if any(word in text for word in ["저렴", "가성비", "가족", "아이", "편하게", "멀어도", "외야", "상단"]):
        return (
            "outfield: 잠실야구장 기준으로 외야석 또는 상단 네이비석을 추천합니다. "
            "가격 부담이 비교적 낮고 전체 경기 흐름을 편하게 보기 좋습니다."
        )
    if any(word in text for word in ["잘 보여", "가까이", "시야", "선수", "내야", "그라운드", "테이블"]):
        return (
            "infield: 잠실야구장 기준으로 내야 그라운드/오렌지석 라인을 추천합니다. "
            "타석, 투수, 내야 수비 움직임이 잘 보여 경기 몰입도가 높습니다."
        )
    return (
        "잠실야구장 좌석 추천을 위해 원하는 관람 스타일을 알려주세요. "
        "예: '응원을 크게 하고 싶어', '가성비가 중요해', '선수가 잘 보이는 곳'."
    )


RESTAURANTS = [
    {
        "name": "잠실 치킨존",
        "place": "inside",
        "condition": "든든한 식사",
        "menu": "치킨, 감자튀김, 콤보 메뉴",
        "location": "잠실야구장 3루 방향 내부 매장 구역",
        "reason": "여러 명이 함께 나눠 먹기 좋고 야구장 분위기와 잘 맞습니다.",
    },
    {
        "name": "버거스페셜 잠실야구장점",
        "place": "inside",
        "condition": "든든한 식사",
        "menu": "햄버거 세트",
        "location": "중앙 출입구 인근",
        "reason": "경기 시작 전에 빠르게 식사하기 좋습니다.",
    },
    {
        "name": "스테디핫도그",
        "place": "inside",
        "condition": "간단한 간식",
        "menu": "핫도그, 소시지",
        "location": "1루 방향 내부 매장 구역",
        "reason": "손에 들고 먹기 편해서 경기 중 간식으로 좋습니다.",
    },
    {
        "name": "잠실야구장 분식 매장",
        "place": "inside",
        "condition": "인기 간식",
        "menu": "떡볶이, 김밥, 어묵",
        "location": "3루 내야 출입구 인근",
        "reason": "야구장에서 가볍게 즐기기 좋은 인기 메뉴입니다.",
    },
    {
        "name": "잠실새내 냉면",
        "place": "outside",
        "condition": "경기 전",
        "menu": "비빔냉면, 물냉면",
        "location": "잠실야구장에서 도보 약 10분, 잠실새내역 인근",
        "reason": "경기 전에 부담 없이 빠르게 먹기 좋습니다.",
    },
    {
        "name": "샤오샤오",
        "place": "outside",
        "condition": "경기 전",
        "menu": "만두, 새우만두",
        "location": "잠실야구장에서 도보 약 12분, 잠실새내 먹자골목 인근",
        "reason": "간단히 포장해서 이동하기 좋습니다.",
    },
    {
        "name": "잠실새내 고깃집",
        "place": "outside",
        "condition": "경기 후",
        "menu": "삼겹살, 목살",
        "location": "잠실야구장에서 도보 약 8분",
        "reason": "경기 후 친구들과 앉아서 이야기 나누기 좋습니다.",
    },
    {
        "name": "백암왕순대 잠실새내점",
        "place": "outside",
        "condition": "경기 후",
        "menu": "순대국, 수육",
        "location": "잠실야구장에서 도보 약 10분",
        "reason": "늦은 경기 후 든든하게 먹기 좋습니다.",
    },
]


def _format_restaurants(restaurants: list[dict[str, str]], title: str) -> str:
    lines = [title]
    for index, restaurant in enumerate(restaurants, start=1):
        lines.extend(
            [
                f"\n{index}. {restaurant['name']}",
                f"- 추천 메뉴: {restaurant['menu']}",
                f"- 위치/거리: {restaurant['location']}",
                f"- 추천 이유: {restaurant['reason']}",
            ]
        )
    lines.append("\n방문 전 실제 영업 여부와 대기 상황은 지도 앱이나 매장 공지로 한 번 더 확인하세요.")
    return "\n".join(lines)


def recommend_food(preferences: str) -> str:
    """OpenAI를 이용해 잠실야구장 안팎 먹거리 추천 답변을 생성합니다."""
    text = preferences.lower()
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        try:
            client = OpenAI(api_key=api_key)
            response = client.responses.create(
                model=os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4.1-mini"),
                input=(
                    "사용자가 LG 트윈스 잠실야구장 직관 먹거리를 물어봤습니다.\n"
                    f"사용자 요청: {preferences}\n\n"
                    "잠실야구장 안 또는 잠실야구장 근처에서 방문하기 좋은 먹거리를 추천해 주세요.\n"
                    "답변은 한국어로 짧고 명확하게 작성하고, 음식점이나 메뉴를 2~3개 추천해 주세요.\n"
                    "각 추천은 아래 형식을 지켜 주세요.\n\n"
                    "1. 음식점/메뉴 이름\n"
                    "- 추천 메뉴:\n"
                    "- 위치/거리:\n"
                    "- 추천 이유:\n\n"
                    "마지막에는 실제 영업 여부, 메뉴, 대기 상황은 지도 앱이나 매장 공지로 "
                    "한 번 더 확인하라고 안내해 주세요."
                ),
            )
            return response.output_text.strip()
        except Exception:
            pass

    if any(word in text for word in ["밖", "근처", "맛집", "음식점", "식당", "경기 전", "경기후", "경기 후"]):
        timing = "경기 후" if any(word in text for word in ["후", "끝나", "끝나고"]) else "경기 전"
        restaurants = [item for item in RESTAURANTS if item["place"] == "outside" and item["condition"] == timing][:3]
        return _format_restaurants(restaurants, f"잠실야구장 근처 {timing} 음식점 추천입니다.")

    if any(word in text for word in ["간식", "가볍", "핫도그"]):
        restaurants = [item for item in RESTAURANTS if item["place"] == "inside" and item["condition"] in ["간단한 간식", "인기 간식"]]
        return _format_restaurants(restaurants, "잠실야구장 안에서 먹기 좋은 간식 추천입니다.")

    restaurants = [item for item in RESTAURANTS if item["place"] == "inside"][:3]
    return _format_restaurants(restaurants, "잠실야구장 안에서 바로 사 먹기 좋은 먹거리 추천입니다.")


def is_food_query(message: str) -> bool:
    compact = re.sub(r"\s+", "", message)
    keywords = ["먹", "맛집", "음식", "음식점", "식당", "치킨", "간식", "메뉴", "밥", "핫도그", "떡볶이"]
    return any(keyword in compact for keyword in keywords)


def recommend_food(preferences: str) -> str:
    """OpenAI web search로 실제 잠실야구장 주변 음식점을 확인해 추천합니다."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return (
            "음식점 추천은 실제 웹 검색이 필요합니다. "
            "OPENAI_API_KEY를 설정한 뒤 다시 질문하면 실제 매장명, 위치, 메뉴, 출처까지 검색해서 알려드릴게요."
        )

    client = OpenAI(api_key=api_key)
    prompt = (
        "사용자가 LG 트윈스 잠실야구장 직관 전후에 갈 실제 음식점/먹거리를 물어봤습니다.\n"
        f"사용자 요청: {preferences}\n\n"
        "최신 웹 검색으로 잠실야구장, 종합운동장역, 잠실새내역 근처에서 실제 존재가 확인되는 곳만 정확히 5개 추천하세요.\n"
        "각 항목에는 실제 매장명, 대표 메뉴, 잠실야구장 기준 위치/거리, 추천 이유, 확인 출처 제목과 URL을 포함하세요.\n"
        "체인점이면 지점명을 확인해서 쓰고, 확실하지 않은 정보는 단정하지 마세요."
    )
    request_args = {
        "model": os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4.1-mini"),
        "input": prompt,
        "tools": [{"type": "web_search_preview"}],
        "tool_choice": {"type": "web_search_preview"},
        "text": {
            "format": {
                "type": "json_schema",
                "name": "food_recommendations",
                "schema": FOOD_JSON_SCHEMA,
                "strict": True,
            }
        },
        "temperature": 0.2,
        "max_output_tokens": 1200,
    }

    try:
        try:
            response = client.responses.create(**request_args)
        except Exception:
            request_args.pop("tool_choice", None)
            response = client.responses.create(**request_args)
        parsed = json.loads(response.output_text)
    except Exception as exc:
        return f"음식점 검색 중 문제가 생겼습니다. API 키와 네트워크 설정을 확인한 뒤 다시 시도해 주세요. ({exc})"

    lines = ["검색으로 확인한 잠실야구장 근처 음식점 추천입니다."]
    for index, item in enumerate(parsed["restaurants"], start=1):
        lines.extend([
            f"\n{index}. {item['name']}",
            f"- 추천 메뉴: {item['menu']}",
            f"- 위치/거리: {item['location']}",
            f"- 추천 이유: {item['reason']}",
            f"- 확인 출처: {item['source_title']} {item['source_url']}",
        ])
    lines.append(f"\n{parsed['notice']}")
    lines.append("방문 전 실제 영업 여부, 메뉴, 대기 상황은 지도 앱이나 매장 공지로 한 번 더 확인하세요.")
    return "\n".join(lines)


def recommend_weather_preparation(query: str) -> str:
    """야구 관람 날씨 준비물과 우천 관련 주의사항을 안내합니다."""
    schedule = search_lg_schedule(query)
    return (
        f"{schedule}\n\n"
        "날씨 준비 팁: 야구장은 저녁에 체감 온도가 내려갈 수 있어 얇은 겉옷을 챙기면 좋습니다. "
        "비 예보가 있으면 우비를 준비하고, 우천 취소 여부는 경기 당일 LG 트윈스/KBO 공식 공지를 확인하세요."
    )


TOOLS = [
    add,
    multiply,
    search_lg_schedule,
    explain_booking_steps,
    recommend_seat_zone,
    recommend_food,
    recommend_weather_preparation,
]

SYSTEM_PROMPT = f"""
당신은 LG 트윈스 경기 일정, 예매, 좌석 선택, 먹거리, 관람 준비를 돕는 한국어 챗봇입니다.
수업 예제처럼 필요하면 도구를 호출해서 DB 일정, 예매 절차, 좌석 추천, 먹거리, 날씨 준비 정보를 확인한 뒤 답하세요.

응답 규칙:
- 한국어로 짧고 명확하게 답합니다.
- 경기 일정 질문은 search_lg_schedule 도구를 사용합니다.
- 예매 방법 질문은 explain_booking_steps 도구를 사용합니다.
- 좌석 추천 질문은 recommend_seat_zone 도구를 사용합니다.
- 먹거리 질문은 recommend_food 도구를 사용합니다.
- 날씨나 준비물 질문은 recommend_weather_preparation 도구를 사용합니다.
- 실제 결제, 좌석 잔여 수량, 가격, 예매 오픈 시간은 확정하지 말고 공식 예매처 확인을 안내합니다.
- 공식 예매 링크는 {BOOKING_LINK} 입니다.
"""


def build_graph():
    if not (ChatOpenAI and os.getenv("OPENAI_API_KEY")):
        return None

    model = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4.1-mini")
    llm = ChatOpenAI(model=model, temperature=0.2)
    llm_with_tools = llm.bind_tools(TOOLS)

    def tool_calling_llm(state: MessagesState):
        return {"messages": [llm_with_tools.invoke(state["messages"])]}

    builder = StateGraph(MessagesState)
    builder.add_node("tool_calling_llm", tool_calling_llm)
    builder.add_node("tools", ToolNode(TOOLS))
    builder.add_edge(START, "tool_calling_llm")
    builder.add_conditional_edges("tool_calling_llm", tools_condition)
    builder.add_edge("tools", "tool_calling_llm")
    return builder.compile()


GRAPH = build_graph()


def infer_visual(message: str, answer: str) -> Visual:
    combined = f"{message}\n{answer}"
    if any(word in combined for word in ["예매", "티켓", "인터파크", "결제", "QR"]):
        return Visual(type="booking_steps", zone=None)
    if "cheer:" in answer or "응원석" in combined:
        return Visual(type="seat_zone", zone="cheer")
    if "outfield:" in answer or "외야석" in combined:
        return Visual(type="seat_zone", zone="outfield")
    if "infield:" in answer or "내야석" in combined:
        return Visual(type="seat_zone", zone="infield")
    if any(word in combined for word in ["먹거리", "맛집", "치킨", "핫도그", "식당"]):
        return Visual(type="food", zone=None)
    if any(word in combined for word in ["날씨", "우비", "우천", "겉옷", "준비물"]):
        return Visual(type="weather", zone=None)
    if any(word in combined for word in ["일정", "경기", "상대", "스코어", "구장"]):
        return Visual(type="schedule", zone=None)
    return Visual(type="none", zone=None)


def fallback_answer(message: str) -> str:
    if is_food_query(message):
        return recommend_food(message)
    if any(word in message for word in ["예매", "티켓", "인터파크", "결제", "QR"]):
        return explain_booking_steps()
    if any(word in message for word in ["먹", "맛집", "음식", "음식점", "식당", "치킨", "간식", "메뉴"]):
        return recommend_food(message)
    if any(word in message for word in ["좌석", "자리", "응원", "내야", "외야", "그라운드", "상단", "시야"]):
        return recommend_seat_zone(message)
    if any(word in message for word in ["날씨", "비", "우천", "준비물", "옷"]):
        return recommend_weather_preparation(message)
    if any(word in message for word in ["일정", "경기", "상대", "오늘", "내일", "모레", "언제", "스코어"]):
        return search_lg_schedule(message)
    return (
        "LG 트윈스 경기 일정, 예매 방법, 좌석 추천, 먹거리, 관람 준비를 도와드릴 수 있어요. "
        "예: '내일 경기 있어?', '응원하기 좋은 좌석 추천해줘', '예매 방법 알려줘'."
    )


@app.get("/health")
async def health():
    return {
        "ok": True,
        "db": DB_PATH.exists(),
        "llm": GRAPH is not None,
        "model": os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4.1-mini"),
    }


@app.get("/api/schedule")
async def schedule(q: str = ""):
    return {"answer": search_lg_schedule(q or "가까운 일정")}


@app.post("/booking-help")
async def booking_help(question: BookingQuestion):
    if is_food_query(question.message):
        answer = recommend_food(question.message)
        return BookingAnswer(answer=answer, visual=Visual(type="food", zone=None)).model_dump()

    if GRAPH and HumanMessage and SystemMessage:
        messages = [SystemMessage(content=SYSTEM_PROMPT)]
        for turn in question.history[-8:]:
            if turn.role == "user":
                messages.append(HumanMessage(content=turn.content))
            else:
                messages.append(AIMessage(content=turn.content))
        messages.append(HumanMessage(content=question.message))
        try:
            result = GRAPH.invoke({"messages": messages})
            answer = result["messages"][-1].content
        except Exception:
            answer = fallback_answer(question.message)
    else:
        answer = fallback_answer(question.message)

    visual = infer_visual(question.message, answer)
    cleaned_answer = re.sub(r"^(cheer|outfield|infield):\s*", "", answer).strip()
    return BookingAnswer(answer=cleaned_answer, visual=visual).model_dump()


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
