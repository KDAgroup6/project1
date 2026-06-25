from __future__ import annotations
import html as html_lib
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
import gradio as gr

# .env 파일에서 네이버 API 키를 읽어옵니다. (python-dotenv 미설치 시에도 동작)
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def _load_env() -> None:
    """실행 위치(cwd)와 스크립트 위치를 기준으로 .env / .venv/.env 를 모두 탐색합니다.

    프로젝트마다 .env 위치가 달라(예: 상위 폴더의 .venv/.env) 어디서 실행해도
    키를 찾을 수 있도록 여러 후보 경로를 순서대로 로드합니다.
    """
    if load_dotenv is None:
        return
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / ".env",
        Path.cwd() / ".venv" / ".env",
        here.parent / ".env",
        here.parent.parent / ".env",
        here.parent.parent / ".venv" / ".env",
    ]
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            load_dotenv(path, override=False)


_load_env()


# 네이버 지도 검색 URL을 만드는 헬퍼.
# 검색어를 그대로 넣으면 해당 식당의 네이버 지도 검색 페이지로 바로 이동합니다.
# (Chatbot 안에서 링크를 누르면 새 탭으로 네이버 지도가 열립니다 = 팝업 효과)
NAVER_MAP_SEARCH = "https://map.naver.com/p/search/"

# 네이버 지역검색(Local Search) API 설정.
# 키는 .env 의 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 에서 읽습니다(코드에 직접 넣지 않음).
NAVER_LOCAL_API = "https://openapi.naver.com/v1/search/local.json"
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")

# 방문 시점별로 네이버에 실제로 검색할 키워드
OUTSIDE_SEARCH_QUERY = {
    "경기 전": "잠실새내역 맛집",
    "경기 후": "잠실새내 회식 맛집",
}


def naver_map_link(query: str) -> str:
    """식당 이름(또는 '식당명 지역')을 네이버 지도 검색 링크로 변환합니다."""
    return NAVER_MAP_SEARCH + urllib.parse.quote(query)


def _strip_tags(text: str | None) -> str:
    """네이버 API 응답의 <b> 등 HTML 태그와 엔티티를 제거합니다."""
    return html_lib.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def search_naver_local(query: str, display: int = 3) -> list[dict[str, str]]:
    """네이버 지역검색 API로 식당을 검색해 카드용 dict 리스트로 반환합니다.

    API 키가 없거나 호출에 실패하면 빈 리스트를 돌려주고,
    호출한 쪽에서 내장(fallback) 데이터를 사용하도록 합니다.
    """
    if not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET):
        return []

    url = NAVER_LOCAL_API + "?" + urllib.parse.urlencode(
        {"query": query, "display": display, "sort": "random"}
    )
    request = urllib.request.Request(
        url,
        headers={
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []

    results = []
    for item in payload.get("items", []):
        name = _strip_tags(item.get("title"))
        if not name:
            continue
        results.append(
            {
                "name": name,
                "place": "outside",
                "category": _strip_tags(item.get("category")),
                "location": item.get("roadAddress") or item.get("address") or "",
                "homepage": item.get("link", ""),
                "naver_query": name,  # 네이버 지도 링크는 식당명으로 검색
            }
        )
    return results


# ---------------------------------------------------------------------------
# 잠실야구장 "내부" 먹거리 데이터
# - 2025~2026 시즌 기준 실제 입점 매장 위주로 정리했습니다.
# - price 는 매장/시즌에 따라 바뀔 수 있어 "대략"으로 안내합니다.
# - 종류(condition): 든든한 식사 / 간단한 간식 / 인기 음식
# ---------------------------------------------------------------------------
INSIDE_RESTAURANTS = [
    {
        "name": "KFC 잠실야구장점",
        "place": "inside",
        "condition": "든든한 식사",
        "menu": "치킨버거 세트, 텐더, 비스킷",
        "price": "버거 세트 약 8,000~9,000원",
        "location": "1~2층 매장 / 3층에도 매장 있어 대기 줄이 짧음",
        "feature": "익숙한 패스트푸드라 실패가 없고, 3층 매장을 이용하면 웨이팅이 적어요.",
    },
    {
        "name": "버거킹 잠실야구장점",
        "place": "inside",
        "condition": "든든한 식사",
        "menu": "와퍼 세트, 너겟",
        "price": "와퍼 세트 약 8,000~10,000원",
        "location": "중앙 출입구 인근 매장 구역",
        "feature": "양이 푸짐해 식사 대용으로 좋고, 경기 시작 전 미리 사두기 좋아요.",
    },
    {
        "name": "BBQ·BHC 치킨 매장",
        "place": "inside",
        "condition": "든든한 식사",
        "menu": "후라이드, 양념치킨",
        "price": "한 마리 약 20,000원 / 컵치킨 약 7,000원",
        "location": "내야 매장 구역",
        "feature": "여러 명이 나눠 먹기 좋은 야구장 대표 메뉴. 컵 단위로도 팔아 혼자도 OK.",
    },
    {
        "name": "스테프핫도그",
        "place": "inside",
        "condition": "간단한 간식",
        "menu": "치즈핫도그, 소시지",
        "price": "약 4,000~5,000원",
        "location": "1루 방향 내부 매장 구역",
        "feature": "한 손으로 들고 먹기 편해 자리에서 응원하며 먹기 좋아요.",
    },
    {
        "name": "명인만두",
        "place": "inside",
        "condition": "간단한 간식",
        "menu": "왕만두, 새우만두",
        "price": "약 5,000~7,000원",
        "location": "내야 매장 구역",
        "feature": "따뜻하고 든든한 간식. 줄이 빠르게 줄어 회전이 좋아요.",
    },
    {
        "name": "스무디킹",
        "place": "inside",
        "condition": "간단한 간식",
        "menu": "과일 스무디, 음료",
        "price": "약 5,000~6,000원",
        "location": "중앙 매장 구역",
        "feature": "더운 날 시원하게 즐기기 좋은 음료. 음식과 함께 곁들이기 좋아요.",
    },
    {
        "name": "갑또리 닭강정",
        "place": "inside",
        "condition": "인기 음식",
        "menu": "닭강정(순살)",
        "price": "약 10,000~13,000원",
        "location": "내야 매장 구역",
        "feature": "야구장 인기 메뉴. 식어도 맛있어 자리에서 두고두고 먹기 좋아요.",
    },
    {
        "name": "이가네 떡볶이",
        "place": "inside",
        "condition": "인기 음식",
        "menu": "떡볶이, 튀김, 어묵",
        "price": "약 5,000~7,000원",
        "location": "내야 매장 구역",
        "feature": "분식 조합으로 가볍게 즐기기 좋은 스테디 인기 메뉴예요.",
    },
    {
        "name": "신철판 야채곱창",
        "place": "inside",
        "condition": "인기 음식",
        "menu": "야채곱창, 막창",
        "price": "약 9,000~12,000원",
        "location": "내야 매장 구역",
        "feature": "야구장에서 보기 드문 곱창 메뉴로, 맥주와 잘 어울려요.",
    },
]


# ---------------------------------------------------------------------------
# 잠실야구장 "주변" 맛집 데이터 (잠실새내역 도보권 위주)
# - 각 식당은 네이버 지도 검색어(naver_query)를 가지고 있어,
#   출력 시 클릭 가능한 네이버 지도 링크로 보여 줍니다.
# - 방문 시점(condition): 경기 전 / 경기 후
# ---------------------------------------------------------------------------
OUTSIDE_RESTAURANTS = [
    {
        "name": "지미존스 잠실새내역점",
        "place": "outside",
        "condition": "경기 전",
        "menu": "샌드위치, 샐러드",
        "price": "샌드위치 약 7,000~9,000원",
        "location": "잠실새내역 4번 출구 도보 약 1분",
        "feature": "빠르게 한 끼 해결하거나 포장해서 입장하기 좋아요.",
        "naver_query": "지미존스 잠실새내역점",
    },
    {
        "name": "윤재갑 양심칼국수",
        "place": "outside",
        "condition": "경기 전",
        "menu": "해물칼국수, 보쌈",
        "price": "칼국수 약 9,000원",
        "location": "잠실새내역 7·8번 출구 지하 연결",
        "feature": "경기 전 따뜻한 국물로 든든하게 채우기 좋은 가성비 맛집이에요.",
        "naver_query": "윤재갑 양심칼국수 잠실",
    },
    {
        "name": "파오파오 잠실새내",
        "place": "outside",
        "condition": "경기 전",
        "menu": "만두, 새우만두",
        "price": "약 5,000~7,000원",
        "location": "잠실야구장 도보 약 12분, 잠실새내 새마을시장 인근",
        "feature": "간단히 먹거나 포장해서 이동하기 좋은 만두 전문점이에요.",
        "naver_query": "파오파오 잠실새내",
    },
    {
        "name": "잠실한우정육식당",
        "place": "outside",
        "condition": "경기 후",
        "menu": "한우 구이",
        "price": "1인 약 25,000~40,000원",
        "location": "잠실새내역 3번 출구 약 280m",
        "feature": "경기 후 친구들과 제대로 회식하기 좋은 정육식당이에요.",
        "naver_query": "잠실한우정육식당",
    },
    {
        "name": "삼거리포차",
        "place": "outside",
        "condition": "경기 후",
        "menu": "해물파전, 골뱅이무침",
        "price": "1인 약 15,000~20,000원",
        "location": "잠실새내역 인근",
        "feature": "경기 이야기를 안주 삼아 한잔하기 좋은 분위기예요.",
        "naver_query": "삼거리포차 잠실새내",
    },
    {
        "name": "88조개",
        "place": "outside",
        "condition": "경기 후",
        "menu": "조개구이, 조개전골",
        "price": "1인 약 20,000~30,000원",
        "location": "잠실새내역 4번 출구 도보 약 3분",
        "feature": "푸짐한 조개구이로 승리(또는 위로)의 뒤풀이를 하기 좋아요.",
        "naver_query": "88조개 잠실새내",
    },
]

RESTAURANTS = INSIDE_RESTAURANTS + OUTSIDE_RESTAURANTS

WELCOME_MESSAGE = (
    "LG 트윈스 직관 먹거리를 추천해 드릴게요.\n\n"
    "먼저 **잠실야구장 안**에서 먹을지, **경기장 근처**에서 먹을지 선택해 주세요."
)

NOTICE = (
    "\n\n> 💡 가격·메뉴·영업시간·입점 여부는 변경될 수 있으니 방문 전 최신 정보를 확인해 주세요. "
    "주변 맛집은 식당 이름을 누르면 네이버 지도로 바로 이동합니다."
)


def find_restaurants(place: str, condition: str) -> list[dict[str, str]]:
    """장소와 선택 조건에 맞는 음식점을 최대 3개 반환합니다."""
    return [
        restaurant
        for restaurant in RESTAURANTS
        if restaurant["place"] == place and restaurant["condition"] == condition
    ][:3]


def format_inside_card(index: int, restaurant: dict[str, str]) -> str:
    """야구장 내부 매장: 가격·종류·특징을 함께 설명합니다."""
    return "\n".join(
        [
            f"### {index}. {restaurant['name']}",
            f"- 대표 메뉴: {restaurant['menu']}",
            f"- 가격(대략): {restaurant['price']}",
            f"- 위치: {restaurant['location']}",
            f"- 특징: {restaurant['feature']}",
        ]
    )


def format_outside_card(index: int, restaurant: dict[str, str]) -> str:
    """주변 맛집: 식당 이름을 네이버 지도 링크로 걸어 줍니다."""
    link = naver_map_link(restaurant["naver_query"])
    return "\n".join(
        [
            f"### {index}. [{restaurant['name']}]({link})",
            f"- 대표 메뉴: {restaurant['menu']}",
            f"- 가격(대략): {restaurant['price']}",
            f"- 위치·거리: {restaurant['location']}",
            f"- 특징: {restaurant['feature']}",
            f"- 🗺️ [네이버 지도에서 보기]({link})",
        ]
    )


def format_live_card(index: int, restaurant: dict[str, str]) -> str:
    """네이버 지역검색 실시간 결과 카드. 식당명을 네이버 지도 링크로 연결합니다."""
    link = naver_map_link(restaurant["naver_query"])
    lines = [f"### {index}. [{restaurant['name']}]({link})"]
    if restaurant.get("category"):
        lines.append(f"- 분류: {restaurant['category']}")
    if restaurant.get("location"):
        lines.append(f"- 주소: {restaurant['location']}")
    if restaurant.get("homepage"):
        lines.append(f"- 홈페이지: {restaurant['homepage']}")
    lines.append(f"- 🗺️ [네이버 지도에서 보기]({link})")
    return "\n".join(lines)


def format_restaurants(restaurants: list[dict[str, str]], title: str) -> str:
    if not restaurants:
        return "조건에 맞는 음식점이 없어요. 다른 조건을 선택해 주세요."

    cards = []
    for index, restaurant in enumerate(restaurants, start=1):
        if restaurant["place"] == "inside":
            cards.append(format_inside_card(index, restaurant))
        else:
            cards.append(format_outside_card(index, restaurant))

    return f"## {title}\n\n" + "\n\n---\n\n".join(cards) + NOTICE


def recommend_inside(category: str) -> str:
    if not category:
        return "원하는 음식 종류를 선택해 주세요."

    restaurants = find_restaurants("inside", category)
    return format_restaurants(restaurants, f"잠실야구장 내부 · {category} 추천")


def recommend_outside(timing: str) -> str:
    if not timing:
        return "방문 시점을 선택해 주세요."

    # 1순위: 네이버 지역검색 API로 실시간 맛집 검색
    query = OUTSIDE_SEARCH_QUERY.get(timing, "잠실새내 맛집")
    live = search_naver_local(query, display=3)
    if live:
        title = f"잠실야구장 주변 · {timing} 추천 (네이버 검색: {query})"
        cards = [format_live_card(i, r) for i, r in enumerate(live, start=1)]
        return f"## {title}\n\n" + "\n\n---\n\n".join(cards) + NOTICE

    # 2순위(대체): API 키가 없거나 호출 실패 시 내장 데이터 사용
    restaurants = find_restaurants("outside", timing)
    return format_restaurants(restaurants, f"잠실야구장 주변 · {timing} 추천")


def add_answer(history: list[dict[str, str]] | None, answer: str) -> list[dict[str, str]]:
    history = history or []
    history.append({"role": "assistant", "content": answer})
    return history


def choose_inside(history: list[dict[str, str]] | None):
    answer = "잠실야구장 안에서 어떤 음식을 찾고 있나요?"

    return (
        gr.update(visible=True),
        gr.update(visible=False),
        add_answer(history, answer),
    )


def choose_outside(history: list[dict[str, str]] | None):
    answer = "경기장 근처 음식점은 언제 방문할 예정인가요?"

    return (
        gr.update(visible=False),
        gr.update(visible=True),
        add_answer(history, answer),
    )


def select_inside(category: str, history: list[dict[str, str]] | None):
    answer = recommend_inside(category)
    return add_answer(history, answer)


def select_outside(timing: str, history: list[dict[str, str]] | None):
    answer = recommend_outside(timing)
    return add_answer(history, answer)


def answer_question(message: str, history: list[dict[str, str]] | None):
    history = history or []
    message = (message or "").strip()

    if not message:
        return history, ""

    history.append({"role": "user", "content": message})
    compact = re.sub(r"\s+", "", message)

    if any(word in compact for word in ["경기전", "시작전", "보기전"]):
        answer = recommend_outside("경기 전")
    elif any(word in compact for word in ["경기후", "끝나고", "종료후", "보고나서"]):
        answer = recommend_outside("경기 후")
    elif any(word in compact for word in ["간식", "핫도그", "만두", "간단하게"]):
        answer = recommend_inside("간단한 간식")
    elif any(word in compact for word in ["인기", "떡볶이", "닭강정", "곱창", "야구장음식"]):
        answer = recommend_inside("인기 음식")
    elif any(word in compact for word in ["든든", "치킨", "햄버거", "버거", "식사"]):
        answer = recommend_inside("든든한 식사")
    elif any(word in compact for word in ["안에서", "내부", "야구장안"]):
        answer = "야구장 내부에서 원하는 종류를 선택해 주세요: 든든한 식사, 간단한 간식, 인기 음식"
    elif any(word in compact for word in ["근처", "주변", "밖에서", "맛집"]):
        answer = "경기장 주변 맛집은 경기 전과 경기 후 중 언제 방문할지 알려 주세요."
    else:
        answer = (
            "질문을 정확히 이해하지 못했어요. 아래처럼 질문해 주세요.\n\n"
            "- 야구장 안에서 간단한 간식 추천해줘\n"
            "- 경기 전에 근처 맛집 알려줘\n"
            "- 경기 끝나고 먹을 곳 추천해줘"
        )

    history.append({"role": "assistant", "content": answer})
    return history, ""


def reset_chat():
    return (
        gr.update(visible=False),
        gr.update(visible=False),
        [{"role": "assistant", "content": WELCOME_MESSAGE}],
        "",
    )


with gr.Blocks(title="LG 트윈스 잠실 먹거리 챗봇") as demo:
    gr.Markdown("# LG 트윈스 잠실 먹거리 챗봇")
    gr.Markdown(
        "잠실야구장 내부 먹거리(가격·종류·특징)와 경기장 주변 맛집(네이버 지도 링크)을 추천합니다."
    )

    chatbot = gr.Chatbot(
        value=[{"role": "assistant", "content": WELCOME_MESSAGE}],
        label="먹거리 안내",
    )

    with gr.Row():
        inside_button = gr.Button("잠실야구장 안에서 먹을래요", variant="primary")
        outside_button = gr.Button("경기장 근처에서 먹을래요", variant="primary")

    with gr.Column(visible=False) as inside_options:
        inside_category = gr.Radio(
            ["든든한 식사", "간단한 간식", "인기 음식"],
            label="원하는 음식 종류",
        )
        inside_submit = gr.Button("추천받기")

    with gr.Column(visible=False) as outside_options:
        outside_timing = gr.Radio(
            ["경기 전", "경기 후"],
            label="방문 시점",
        )
        outside_submit = gr.Button("추천받기")

    with gr.Row():
        question = gr.Textbox(
            placeholder="예: 경기 전에 근처 맛집 알려줘",
            label="직접 질문하기",
            scale=5,
        )
        ask_button = gr.Button("전송", scale=1)

    reset_button = gr.Button("처음으로 돌아가기")

    inside_button.click(
        choose_inside,
        inputs=chatbot,
        outputs=[inside_options, outside_options, chatbot],
    )

    outside_button.click(
        choose_outside,
        inputs=chatbot,
        outputs=[inside_options, outside_options, chatbot],
    )

    inside_submit.click(
        select_inside,
        inputs=[inside_category, chatbot],
        outputs=chatbot,
    )

    outside_submit.click(
        select_outside,
        inputs=[outside_timing, chatbot],
        outputs=chatbot,
    )

    question.submit(
        answer_question,
        inputs=[question, chatbot],
        outputs=[chatbot, question],
    )

    ask_button.click(
        answer_question,
        inputs=[question, chatbot],
        outputs=[chatbot, question],
    )

    reset_button.click(
        reset_chat,
        outputs=[inside_options, outside_options, chatbot, question],
    )


if __name__ == "__main__":
    demo.launch()
