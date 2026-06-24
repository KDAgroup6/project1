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
다음 사실만을 근거로 짧고 명확하게 한국어로 답변하세요.

- 예매처: 인터파크 티켓 ({BOOKING_LINK})
- 예매 시작: 경기일 기준 4~5일 전 오후 2시부터 (홈경기만 해당)
- 원정 경기는 상대 구단의 예매처를 이용해야 합니다
- 홈구장: 잠실종합운동장 야구장
- 모바일 앱에서도 동일하게 예매 가능하며, 전자티켓/QR코드로 입장합니다
- 실제 결제나 좌석 예약은 이 챗봇에서 처리할 수 없으며, 인터파크 티켓 사이트에서 직접 진행해야 합니다

위 사실에 없는 내용(좌석 잔여 수량, 가격, 실시간 예매 현황 등)은 모른다고 답하고, 공식 사이트 확인을 안내하세요."""


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
    try:
        response = client.responses.create(
            model=DEFAULT_MODEL,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question.message},
            ],
            temperature=0.3,
            max_output_tokens=400,
        )
        answer = response.output_text
    except Exception:
        answer = "지금은 답변을 가져올 수 없어요. 인터파크 티켓에서 직접 확인해 주세요."

    return {"answer": answer, "link": BOOKING_LINK}


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
