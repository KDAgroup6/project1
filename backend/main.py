from dotenv import load_dotenv
import os

load_dotenv(override=True)

from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from openai import OpenAI

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI()
DEFAULT_MODEL = os.getenv("OPENAI_DEFAULT_MODEL")

BOOKING_LINK = "https://ticket.interpark.com"

SYSTEM_PROMPT = f"""당신은 LG 트윈스 야구 경기 직관을 준비하는 사용자를 돕는 예매 안내 챗봇입니다.
한국어로 짧고 명확하게 답변하세요. 답변은 반드시 주어진 JSON 스키마 형식으로만 응답하세요.

다음은 확인된 사실입니다:
- 예매처: 인터파크 티켓 ({BOOKING_LINK})
- 예매 시작: 경기일 기준 4~5일 전 오후 2시부터 (홈경기만 해당)
- 원정 경기는 상대 구단의 예매처를 이용해야 합니다
- 홈구장: 잠실종합운동장 야구장
- 모바일 앱에서도 동일하게 예매 가능하며, 전자티켓/QR코드로 입장합니다
- 실제 결제나 좌석 예약은 이 챗봇에서 처리할 수 없으며, 인터파크 티켓 사이트에서 직접 진행해야 합니다
- 지하철 종합운동장역에서 1루 방향은 5번 출구, 3루·모바일티켓 방향은 6번 출구가 더 빠릅니다 (팬 후기 기반 정보, 공식 확인 아님)
- 1루 게이트는 역에서 왼쪽 방향, 3루 게이트는 오른쪽 방향에 있습니다 (팬 후기 기반 정보)
- 외야 출입구는 내야 게이트보다 더 바깥쪽에 있고, 내야 출입구는 총 4개로 좌석 블록별로 입장 게이트가 다릅니다 (팬 후기 기반 정보)
- LG 홈경기 기준 1루 = LG 팬 자리, 3루 = 원정팀 자리입니다
- 위 게이트 관련 정보는 정확한 번호까지는 보장하지 않으므로, 정확한 번호는 티켓 QR/현장 안내판 확인을 안내하세요

좌석 잔여 수량, 가격, 실시간 예매 현황은 알 수 없다고 답하고 공식 사이트 확인을 안내하세요.

위 사실에 없는 질문(주차, 매장 위치, 경기 취소 여부 등)을 받으면 웹 검색 도구를 사용해 답변하고, 검색 결과를 바탕으로 답했다는 점을 답변에 짧게 표시하세요.

좌석 추천 요청을 받으면:
1. 예산, 동행 인원, 응원 성향(조용히 관람 vs 활발한 응원) 중 아직 모르는 정보를 한 번에 1~2개씩 되물으세요. 이때 visual.type은 "none"으로 답변하세요.
2. 충분한 정보가 모이면 "infield"(내야석, 시야 좋음·가격 높음), "outfield"(외야석, 가격 합리적·가족/단체 추천), "cheer"(응원석, 응원 분위기 최고) 중 하나로 추천하고 visual.type을 "seat_zone", visual.zone을 해당 구역으로 답변하세요.

예매 방법을 묻는 질문을 받으면 visual.type을 "booking_steps"로 답변하세요 (zone은 null).

그 외 일반적인 질문은 visual.type을 "none"으로 답변하세요 (zone은 null)."""


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class BookingQuestion(BaseModel):
    message: str
    history: list[ChatTurn] = []


class Visual(BaseModel):
    type: Literal["none", "seat_zone", "booking_steps"]
    zone: Optional[Literal["infield", "outfield", "cheer"]] = None


class BookingAnswer(BaseModel):
    answer: str
    visual: Visual


ANSWER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "visual": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["none", "seat_zone", "booking_steps"],
                },
                "zone": {
                    "type": ["string", "null"],
                    "enum": ["infield", "outfield", "cheer", None],
                },
            },
            "required": ["type", "zone"],
            "additionalProperties": False,
        },
    },
    "required": ["answer", "visual"],
    "additionalProperties": False,
}


@app.post("/booking-help")
async def booking_help(question: BookingQuestion):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in question.history:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": question.message})

    try:
        response = client.responses.create(
            model=DEFAULT_MODEL,
            input=messages,
            tools=[{"type": "web_search_preview"}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "booking_answer",
                    "schema": ANSWER_JSON_SCHEMA,
                    "strict": True,
                }
            },
            temperature=0.3,
            max_output_tokens=600,
        )
        parsed = BookingAnswer.model_validate_json(response.output_text)
        answer = parsed.answer
        visual = parsed.visual.model_dump()
    except Exception:
        answer = "지금은 답변을 가져올 수 없어요. 인터파크 티켓에서 직접 확인해 주세요."
        visual = {"type": "none", "zone": None}

    return {"answer": answer, "link": BOOKING_LINK, "visual": visual}


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
