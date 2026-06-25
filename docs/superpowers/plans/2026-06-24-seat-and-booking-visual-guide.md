# 좌석 추천 + 예매 방법 시각 안내 + 웹 검색 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LG 트윈스 예매 챗봇에 (1) 멀티턴 대화 기록, (2) 좌석 추천 + 구장 지도 SVG, (3) 예매 방법 체크리스트, (4) 시스템 프롬프트 밖 질문에 대한 웹 검색 응답 기능을 추가한다.

**Architecture:** 프론트엔드가 대화 기록을 메모리에 들고 매 요청마다 백엔드로 전달한다. 백엔드는 OpenAI Responses API를 JSON 스키마 구조화 출력(`answer` + `visual`) + 웹 검색 도구와 함께 호출한다. 그림(SVG/체크리스트) 마크업은 프론트엔드 고정 템플릿이며, 백엔드는 `visual.type`/`visual.zone` 값만 결정한다.

**Tech Stack:** FastAPI, Pydantic, OpenAI Python SDK (Responses API), 순수 HTML/CSS/SVG (외부 라이브러리 없음)

**참고:** 이 프로젝트는 자동화 테스트 스위트가 없는 소규모 테스트 프로젝트다 (스펙 문서 `docs/superpowers/specs/2026-06-24-seat-and-booking-visual-guide-design.md`의 "테스트" 섹션에서 수동 검증으로 명시 합의됨). 따라서 각 태스크의 검증은 pytest가 아니라 `curl`/브라우저를 이용한 수동 확인으로 진행한다.

---

### Task 1: 백엔드 — 데이터 모델 및 JSON 스키마 정의

**Files:**
- Modify: `backend/main.py:1-26` (import 구역과 `BOOKING_LINK` 사이)

- [ ] **Step 1: 모델/스키마 코드 추가**

`backend/main.py`의 기존 `class BookingQuestion(BaseModel):` 블록(현재 41-42번 줄)을 다음 코드로 통째로 교체한다.

```python
from typing import Literal, Optional


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
```

Also add `from typing import Literal, Optional` near the top imports (with the other stdlib imports, above `from pathlib import Path`).

- [ ] **Step 2: 문법 확인**

Run: `cd backend && "./.venv/Scripts/python.exe" -c "import main"`
Expected: 에러 없이 종료 (이 시점엔 아직 `/booking-help`가 옛 코드를 참조해 깨질 수 있음 — 다음 태스크에서 고친다. `ImportError`나 `SyntaxError`만 없으면 OK)

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: add chat history and structured visual response models"
```

---

### Task 2: 백엔드 — 시스템 프롬프트 확장

**Files:**
- Modify: `backend/main.py` (`SYSTEM_PROMPT` 정의부, 현재 28-38번 줄)

- [ ] **Step 1: SYSTEM_PROMPT 교체**

기존 `SYSTEM_PROMPT = f"""..."""` 블록 전체를 다음으로 교체한다.

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/main.py
git commit -m "feat: expand system prompt with gate facts, seat flow, and search instructions"
```

---

### Task 3: 백엔드 — `/booking-help` 엔드포인트 재작성

**Files:**
- Modify: `backend/main.py` (`@app.post("/booking-help")` 블록, Task 1 적용 후 기준 약 60-75번 줄 부근)

- [ ] **Step 1: 엔드포인트 본문 교체**

```python
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
```

이 코드가 기존의 `try/except` 블록을 완전히 대체한다 (`response = client.responses.create(...)`부터 `return {"answer": answer, "link": BOOKING_LINK}`까지 전부 교체).

- [ ] **Step 2: 서버 기동 확인**

Run:
```bash
cd backend
"./.venv/Scripts/python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
```
Expected: `Uvicorn running on http://127.0.0.1:8000` 로그가 뜨고 에러 없이 대기 상태가 됨. 확인 후 Ctrl+C로 종료(또는 다음 태스크에서 계속 쓸 거면 백그라운드로 둔다).

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: support chat history, structured visual output, and web search in booking-help"
```

---

### Task 4: 백엔드 — 수동 스모크 테스트 3종

**Files:** (코드 변경 없음, 검증만)

- [ ] **Step 1: 서버 실행 (백그라운드)**

Run (backend 디렉터리에서):
```bash
"./.venv/Scripts/python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000 > server.log 2>&1 &
```
Expected: 프로세스가 시작되고 `server.log`에 `Application startup complete.` 기록됨.

- [ ] **Step 2: 일반 질문 (visual: none) 확인**

Run:
```bash
curl -s http://127.0.0.1:8000/booking-help -X POST -H "Content-Type: application/json" -d "{\"message\":\"hello\",\"history\":[]}"
```
Expected: JSON 응답에 `"visual":{"type":"none","zone":null}` 포함, `answer`에 인사/안내 텍스트.

- [ ] **Step 3: 예매 방법 질문 (visual: booking_steps) 확인**

Run:
```bash
curl -s http://127.0.0.1:8000/booking-help -X POST -H "Content-Type: application/json" -d "{\"message\":\"how do I book a ticket\",\"history\":[]}"
```
Expected: `"visual":{"type":"booking_steps","zone":null}` 포함.

- [ ] **Step 4: 좌석 추천 멀티턴 흐름 확인**

Run (1차 — 정보 부족, visual: none 기대):
```bash
curl -s http://127.0.0.1:8000/booking-help -X POST -H "Content-Type: application/json" -d "{\"message\":\"recommend a seat for me\",\"history\":[]}"
```
Expected: `"visual":{"type":"none","zone":null}` 이고 `answer`에 예산/인원/응원 성향을 되묻는 내용.

Run (2차 — 직전 답변을 history에 넣고 충분한 정보 제공, visual: seat_zone 기대):
```bash
curl -s http://127.0.0.1:8000/booking-help -X POST -H "Content-Type: application/json" -d "{\"message\":\"budget is tight, going alone, want to cheer loudly\",\"history\":[{\"role\":\"user\",\"content\":\"recommend a seat for me\"},{\"role\":\"assistant\",\"content\":\"(1차 응답의 answer 텍스트를 그대로 붙여넣기)\"}]}"
```
Expected: `"visual":{"type":"seat_zone","zone":"cheer"}` (또는 모델 판단에 따라 `outfield`) 처럼 `zone`이 `null`이 아닌 값으로 채워짐.

- [ ] **Step 5: 웹 검색 트리거 질문 확인**

Run:
```bash
curl -s http://127.0.0.1:8000/booking-help -X POST -H "Content-Type: application/json" -d "{\"message\":\"잠실야구장 주차장 있어?\",\"history\":[]}"
```
Expected: 200 OK와 함께 `answer`에 검색 기반임을 알리는 문구 포함. **만약 OpenAI API가 `tools` + `text.format` 조합을 거부하는 에러를 반환하면(서버 로그에 예외 스택 확인)**, `text.format` 강제를 일단 빼고 (tools만 사용, 일반 텍스트 응답 후 `visual: none`으로 고정) 동작을 우선 확보한 뒤, 이 계획의 Task 3로 돌아가 별도 후속 태스크로 구조화 출력 재도입 여부를 사용자와 논의한다.

- [ ] **Step 6: 서버 종료**

Run: `taskkill //F //IM python.exe` (Windows) 또는 해당 프로세스를 Ctrl+C로 종료.

---

### Task 5: 프론트엔드 — `visuals.js` 생성 (좌석 지도 + 예매 체크리스트 템플릿)

**Files:**
- Create: `frontend/visuals.js`

- [ ] **Step 1: 파일 작성**

```javascript
const SEAT_ZONE_INFO = {
  infield: {
    label: "내야석",
    desc: "시야가 좋고 경기를 가까이서 볼 수 있어요. 가격대가 높은 편입니다.",
  },
  outfield: {
    label: "외야석",
    desc: "가격이 합리적이고 가족/단체 관람에 좋아요. 거리는 다소 먼 편입니다.",
  },
  cheer: {
    label: "응원석",
    desc: "응원 열기를 가장 가까이서 느낄 수 있는 활동적인 구역이에요.",
  },
};

function seatFill(zoneKey, activeZone, activeColor, baseColor) {
  return zoneKey === activeZone ? activeColor : baseColor;
}

function seatStroke(zoneKey, activeZone) {
  return zoneKey === activeZone
    ? 'stroke="#1a73e8" stroke-width="3"'
    : 'stroke="#a9cdef" stroke-width="1"';
}

function buildSeatZoneSvg(zone) {
  return `
    <svg width="260" height="180" viewBox="0 0 260 180" class="seat-map">
      <ellipse cx="130" cy="100" rx="120" ry="60" fill="#dff5d8" stroke="#bcdcae" />
      <ellipse cx="130" cy="100" rx="60" ry="30" fill="#fff8c4" stroke="#e8dd8f" />
      <text x="130" y="104" font-size="11" text-anchor="middle" fill="#7a6a1a">그라운드</text>

      <rect x="6" y="60" width="55" height="80" rx="8" fill="${seatFill("outfield", zone, "#a9d4ff", "#cfe9ff")}" ${seatStroke("outfield", zone)} />
      <text x="33" y="103" font-size="10" text-anchor="middle" fill="#1a5a9e">외야석</text>

      <rect x="199" y="60" width="55" height="80" rx="8" fill="${seatFill("outfield", zone, "#a9d4ff", "#cfe9ff")}" ${seatStroke("outfield", zone)} />
      <text x="226" y="103" font-size="10" text-anchor="middle" fill="#1a5a9e">외야석</text>

      <rect x="60" y="10" width="60" height="40" rx="8" fill="${seatFill("infield", zone, "#ffb3b3", "#ffd9d9")}" ${seatStroke("infield", zone)} />
      <text x="90" y="33" font-size="9" text-anchor="middle" fill="#9e3a3a">1루 내야</text>

      <rect x="140" y="10" width="60" height="40" rx="8" fill="${seatFill("infield", zone, "#ffb3b3", "#ffd9d9")}" ${seatStroke("infield", zone)} />
      <text x="170" y="33" font-size="9" text-anchor="middle" fill="#9e3a3a">3루 내야</text>

      <rect x="95" y="145" width="70" height="22" rx="6" fill="${seatFill("cheer", zone, "#dba9ff", "#f0d9ff")}" ${seatStroke("cheer", zone)} />
      <text x="130" y="160" font-size="9" text-anchor="middle" fill="#6a2a9e">응원석</text>
    </svg>
  `;
}

function renderSeatZone(container, zone) {
  const info = SEAT_ZONE_INFO[zone];
  if (!info) return;
  const wrap = document.createElement("div");
  wrap.className = "visual-card";
  wrap.innerHTML = `
    ${buildSeatZoneSvg(zone)}
    <p class="visual-caption"><b>${info.label}</b> 추천 — ${info.desc}</p>
  `;
  container.appendChild(wrap);
  container.scrollTop = container.scrollHeight;
}

const BOOKING_STEPS = [
  { title: "인터파크 티켓 접속", desc: "ticket.interpark.com 에서 LG 트윈스 경기 검색" },
  { title: "날짜·홈경기 확인", desc: "원하는 경기일이 홈경기인지 확인 (원정 경기는 상대 구단 예매처 이용)" },
  { title: "좌석 선택", desc: "구역/좌석을 선택하고 결제 진행" },
  { title: "결제 및 전자티켓 수령", desc: "결제 완료 후 모바일 전자티켓(QR코드)으로 입장" },
];

function renderBookingSteps(container) {
  const wrap = document.createElement("div");
  wrap.className = "visual-card";
  const items = BOOKING_STEPS.map(
    (step, i) => `
    <div class="step-item">
      <span class="step-number">${i + 1}</span>
      <div>
        <div class="step-title">${step.title}</div>
        <div class="step-desc">${step.desc}</div>
      </div>
    </div>`
  ).join("");
  wrap.innerHTML = `<div class="steps-list">${items}</div>`;
  container.appendChild(wrap);
  container.scrollTop = container.scrollHeight;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/visuals.js
git commit -m "feat: add seat zone svg and booking steps checklist templates"
```

---

### Task 6: 프론트엔드 — `index.html`에 스타일/스크립트 태그 추가

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: `<style>` 블록 끝(`button { padding: 8px 16px; }` 다음)에 CSS 추가**

```css
  .visual-card {
    background: #fafafa;
    border: 1px solid #eee;
    border-radius: 8px;
    padding: 10px;
    margin-bottom: 10px;
  }
  .visual-caption {
    font-size: 13px;
    margin: 6px 0 0;
    text-align: center;
  }
  .steps-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .step-item {
    display: flex;
    gap: 8px;
    align-items: flex-start;
  }
  .step-number {
    flex-shrink: 0;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: #1a73e8;
    color: white;
    font-size: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .step-title {
    font-size: 13px;
    font-weight: bold;
  }
  .step-desc {
    font-size: 12px;
    color: #555;
  }
```

- [ ] **Step 2: `<script src="script.js"></script>` 바로 위에 `visuals.js` 태그 추가**

```html
  <script src="visuals.js"></script>
  <script src="script.js"></script>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: add styles and script tag for visual cards"
```

---

### Task 7: 프론트엔드 — `script.js`에 대화 기록 + 시각 자료 렌더링 추가

**Files:**
- Modify: `frontend/script.js`

- [ ] **Step 1: 전체 파일 교체**

```javascript
const API_URL = "http://localhost:8000/booking-help";

const form = document.getElementById("chat-form");
const input = document.getElementById("message");
const log = document.getElementById("log");

let history = [];

function addBubble(text, sender) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${sender}`;
  bubble.textContent = text;
  log.appendChild(bubble);
  log.scrollTop = log.scrollHeight;
  return bubble;
}

function addBookingLink(url) {
  const link = document.createElement("a");
  link.className = "booking-link";
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = "🎫 인터파크 티켓에서 예매하기";
  log.appendChild(link);
  log.scrollTop = log.scrollHeight;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) return;

  addBubble(message, "user");
  input.value = "";

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history }),
    });
    const data = await response.json();
    addBubble(data.answer, "bot");
    history.push({ role: "user", content: message });
    history.push({ role: "assistant", content: data.answer });

    if (data.visual && data.visual.type === "seat_zone") {
      renderSeatZone(log, data.visual.zone);
    } else if (data.visual && data.visual.type === "booking_steps") {
      renderBookingSteps(log);
    }

    addBookingLink(data.link);
  } catch (error) {
    addBubble("서버에 연결할 수 없습니다.", "bot");
  }
});
```

- [ ] **Step 2: Commit**

```bash
git add frontend/script.js
git commit -m "feat: track chat history and render seat/booking visuals in chat"
```

---

### Task 8: 엔드투엔드 수동 확인 (브라우저)

**Files:** (코드 변경 없음)

- [ ] **Step 1: 서버 기동**

Run (backend 디렉터리에서):
```bash
"./.venv/Scripts/python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
```

- [ ] **Step 2: 브라우저로 `http://localhost:8000` 접속**

Expected: 챗봇 UI가 뜬다 (FastAPI가 `frontend/`를 `/`에 정적 서빙하므로 별도 서버 불필요).

- [ ] **Step 3: 시나리오 확인**

1. "좌석 추천해줘" 입력 → 예산/인원 등 되묻는 답변만 오고 그림 없음 → 답에 정보를 주는 후속 메시지 입력 → 구장 지도 SVG가 해당 구역 강조 표시되어 나타나는지 확인
2. "예매 어떻게 해?" 입력 → 4단계 체크리스트가 나타나는지 확인
3. "잠실 근처에 주차장 있어?" 입력 → 답변이 오는지(웹 검색 경유) 확인, 응답이 다소 느려지는 것은 정상
4. "안녕" 같은 잡담 입력 → 그림 없이 텍스트만 응답되는지 확인

- [ ] **Step 4: 문제 없으면 서버 종료, 최종 커밋 여부 확인**

Run: `git status` → 변경 사항이 모두 이전 태스크에서 커밋되어 깨끗한 상태인지 확인.
