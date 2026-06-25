from __future__ import annotations
import re
import gradio as gr


# PRD 8.4 기능에 필요한 최소 음식점 데이터입니다.
# 메뉴와 영업시간은 바뀔 수 있으므로 실제 방문 전 확인 안내를 함께 제공합니다.
RESTAURANTS = [
    {
        "name": "잠실 원샷치킨",
        "place": "inside",
        "condition": "든든한 식사",
        "menu": "치킨, 감자튀김, 콤보 메뉴",
        "location": "3루 방향 내부 매장 구역",
        "reason": "여러 명이 함께 나누어 먹기 좋아요.",
    },
    {
        "name": "버거앤프라이즈 잠실야구장점",
        "place": "inside",
        "condition": "든든한 식사",
        "menu": "햄버거 세트",
        "location": "중앙 출입구 인근",
        "reason": "경기 시작 전에 빠르게 식사하기 좋아요.",
    },
    {
        "name": "스테프핫도그",
        "place": "inside",
        "condition": "간단한 간식",
        "menu": "핫도그, 소시지",
        "location": "1루 방향 내부 매장 구역",
        "reason": "한 손으로 들고 먹기 편해요.",
    },
    {
        "name": "잠실야구장 분식 매장",
        "place": "inside",
        "condition": "인기 음식",
        "menu": "떡볶이, 튀김, 닭강정",
        "location": "3루 내야 출입구 인근",
        "reason": "야구장에서 가볍게 즐기기 좋은 인기 메뉴예요.",
    },
    {
        "name": "해주냉면",
        "place": "outside",
        "condition": "경기 전",
        "menu": "비빔냉면, 물냉면",
        "location": "잠실야구장에서 도보 약 10분, 잠실새내역 인근",
        "reason": "경기 전에 부담 없이 빠르게 먹기 좋은 잠실새내 대표 냉면집이에요.",
    },
    {
        "name": "파오파오",
        "place": "outside",
        "condition": "경기 전",
        "menu": "만두, 새우만두",
        "location": "잠실야구장에서 도보 약 12분, 잠실새내 새마을시장 인근",
        "reason": "경기 전에 간단하게 먹거나 포장해서 이동하기 좋아요.",
    },
    {
        "name": "잠실새내 고깃집",
        "place": "outside",
        "condition": "경기 후",
        "menu": "삼겹살, 목살",
        "location": "잠실야구장에서 도보 약 8분",
        "reason": "친구들과 경기 이야기를 나누며 식사하기 좋아요.",
    },
    {
        "name": "백암왕순대 잠실새내점",
        "place": "outside",
        "condition": "경기 후",
        "menu": "순대국, 수육",
        "location": "잠실야구장에서 도보 약 10분",
        "reason": "저녁 경기 후 따뜻하고 든든하게 먹기 좋아요.",
    },
]

WELCOME_MESSAGE = (
    "LG 트윈스 직관 먹거리를 추천해 드릴게요.\n\n"
    "먼저 **잠실야구장 안**에서 먹을지, **경기장 근처**에서 먹을지 선택해 주세요."
)

NOTICE = (
    "\n\n> 음식점의 입점 여부, 메뉴와 영업시간은 변경될 수 있으니 "
    "방문 전에 최신 정보를 확인해 주세요."
)


def find_restaurants(place: str, condition: str) -> list[dict[str, str]]:
    """장소와 선택 조건에 맞는 음식점을 최대 3개 반환합니다."""
    return [
        restaurant
        for restaurant in RESTAURANTS
        if restaurant["place"] == place and restaurant["condition"] == condition
    ][:3]


def format_restaurants(restaurants: list[dict[str, str]], title: str) -> str:
    if not restaurants:
        return "조건에 맞는 음식점이 없어요. 다른 조건을 선택해 주세요."

    cards = []

    for index, restaurant in enumerate(restaurants, start=1):
        cards.append(
            "\n".join(
                [
                    f"### {index}. {restaurant['name']}",
                    f"- 대표 메뉴: {restaurant['menu']}",
                    f"- 위치·거리: {restaurant['location']}",
                    f"- 추천 이유: {restaurant['reason']}",
                ]
            )
        )

    return f"## {title}\n\n" + "\n\n---\n\n".join(cards) + NOTICE


def recommend_inside(category: str) -> str:
    if not category:
        return "원하는 음식 종류를 선택해 주세요."

    restaurants = find_restaurants("inside", category)
    return format_restaurants(restaurants, f"잠실야구장 내부 · {category} 추천")


def recommend_outside(timing: str) -> str:
    if not timing:
        return "방문 시점을 선택해 주세요."

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
    elif any(word in compact for word in ["간식", "핫도그", "간단하게"]):
        answer = recommend_inside("간단한 간식")
    elif any(word in compact for word in ["인기", "떡볶이", "닭강정", "야구장음식"]):
        answer = recommend_inside("인기 음식")
    elif any(word in compact for word in ["든든", "치킨", "햄버거", "식사"]):
        answer = recommend_inside("든든한 식사")
    elif any(word in compact for word in ["안에서", "내부", "야구장안"]):
        answer = "야구장 내부에서 원하는 종류를 선택해 주세요: 든든한 식사, 간단한 간식, 인기 음식"
    elif any(word in compact for word in ["근처", "주변", "밖에서"]):
        answer = "경기장 주변 음식점은 경기 전과 경기 후 중 언제 방문할지 알려 주세요."
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
    gr.Markdown("잠실야구장 내부 음식점과 경기장 주변 맛집을 간단하게 추천합니다.")

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