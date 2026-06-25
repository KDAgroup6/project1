const API_URL = "/api/chat";
const DATES_URL = "/api/calendar-dates";

const form = document.getElementById("chat-form");
const input = document.getElementById("message");
const log = document.getElementById("log");
const toolName = document.getElementById("tool-name");
const resultContent = document.getElementById("result-content");
const calendarGrid = document.getElementById("calendar-grid");
const monthLabel = document.getElementById("month-label");
const prevMonth = document.getElementById("prev-month");
const nextMonth = document.getElementById("next-month");

let history = [];
let gameDates = new Map();
let cursor = new Date();
let selectedDate = null;
const todayKey = formatDate(new Date());

const TOOL_LABELS = {
  get_lg_twins_schedule: "경기 일정",
  guide_lg_twins_booking: "예매 도우미",
  recommend_outfit_by_weather: "날씨 복장 추천",
  recommend_jamsil_food: "먹거리 추천",
};

input.placeholder = `예: 오늘(${todayKey}) 경기 날씨에 맞는 옷 추천해줘`;

const SEAT_ZONE_INFO = {
  infield: {
    label: "내야석",
    desc: "경기를 가까이 보고 싶거나 시야를 중시할 때 좋아요.",
  },
  outfield: {
    label: "외야석",
    desc: "가격 부담을 낮추고 편하게 보고 싶을 때 좋아요.",
  },
  cheer: {
    label: "응원석",
    desc: "LG 응원 분위기를 제대로 느끼고 싶을 때 좋아요.",
  },
};

function formatDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addBubble(text, sender, extraClass = "") {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${sender} ${extraClass}`.trim();
  bubble.textContent = text;
  log.appendChild(bubble);
  log.scrollTop = log.scrollHeight;
  return bubble;
}

function addActionLink(url, label) {
  const link = document.createElement("a");
  link.className = "action-link";
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = label;
  log.appendChild(link);
  log.scrollTop = log.scrollHeight;
}

function pickSeatZone(answer, result) {
  const text = `${answer || ""} ${JSON.stringify(result || {})}`;
  if (/응원|cheer/i.test(text)) return "cheer";
  if (/외야|outfield/i.test(text)) return "outfield";
  return "infield";
}

function wantsBookingSteps(result) {
  return ["booking", "booking_and_seat"].includes(result.intent || "booking");
}

function wantsSeatVisual(result) {
  return ["seat", "booking_and_seat"].includes(result.intent || "");
}

function seatFill(zone, active) {
  return zone === active ? "#c3042f" : "#fff1f4";
}

function seatText(zone, active) {
  return zone === active ? "#ffffff" : "#221f20";
}

function renderSeatMap(zone) {
  const info = SEAT_ZONE_INFO[zone] || SEAT_ZONE_INFO.infield;
  const wrap = document.createElement("div");
  wrap.className = "visual-card";
  wrap.innerHTML = `
    <svg viewBox="0 0 320 220" class="seat-map" role="img" aria-label="좌석 추천 구역">
      <rect x="12" y="12" width="296" height="196" rx="8" fill="#fff" stroke="#e5dce0" />
      <path d="M72 154 Q160 62 248 154" fill="none" stroke="#221f20" stroke-width="8" stroke-linecap="round" />
      <path d="M95 148 Q160 92 225 148" fill="none" stroke="#c3042f" stroke-width="5" stroke-linecap="round" />
      <ellipse cx="160" cy="142" rx="54" ry="28" fill="#f4f0f2" stroke="#d8ccd1" />
      <text x="160" y="147" text-anchor="middle" font-size="12" fill="#6d6669">GROUND</text>

      <rect x="60" y="42" width="74" height="48" rx="6" fill="${seatFill("infield", zone)}" stroke="#c3042f" />
      <text x="97" y="71" text-anchor="middle" font-size="13" font-weight="700" fill="${seatText("infield", zone)}">1루 내야</text>

      <rect x="186" y="42" width="74" height="48" rx="6" fill="${seatFill("infield", zone)}" stroke="#c3042f" />
      <text x="223" y="71" text-anchor="middle" font-size="13" font-weight="700" fill="${seatText("infield", zone)}">3루 내야</text>

      <rect x="24" y="112" width="62" height="58" rx="6" fill="${seatFill("outfield", zone)}" stroke="#c3042f" />
      <text x="55" y="145" text-anchor="middle" font-size="13" font-weight="700" fill="${seatText("outfield", zone)}">외야</text>

      <rect x="234" y="112" width="62" height="58" rx="6" fill="${seatFill("outfield", zone)}" stroke="#c3042f" />
      <text x="265" y="145" text-anchor="middle" font-size="13" font-weight="700" fill="${seatText("outfield", zone)}">외야</text>

      <rect x="118" y="176" width="84" height="24" rx="6" fill="${seatFill("cheer", zone)}" stroke="#c3042f" />
      <text x="160" y="193" text-anchor="middle" font-size="12" font-weight="700" fill="${seatText("cheer", zone)}">응원석</text>
    </svg>
    <p class="visual-caption"><strong>${info.label}</strong> 추천 · ${info.desc}</p>
  `;
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
}

function renderBookingSteps(result) {
  const wrap = document.createElement("div");
  wrap.className = "visual-card";
  const steps = (result.steps || []).map((step, index) => `
    <div class="step-row">
      <span>${index + 1}</span>
      <p>${step}</p>
    </div>
  `).join("");
  wrap.innerHTML = `<div class="steps-list">${steps}</div>`;
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
}

function setResult(data) {
  if (!data || !data.tool_result) return;
  const result = data.tool_result;

  if (data.tool === "get_lg_twins_schedule") {
    resultContent.textContent = result.summary || "일정 정보가 없습니다.";
    return;
  }

  if (data.tool === "guide_lg_twins_booking") {
    if (result.intent === "seat") {
      resultContent.textContent = Object.values(result.seat_tips).join("\n");
    } else {
      resultContent.textContent = `${result.steps.join("\n")}\n\n${result.notice}`;
    }
    return;
  }

  if (data.tool === "recommend_outfit_by_weather") {
    if (result.error) {
      resultContent.textContent = result.error;
      return;
    }
    const weather = result.weather;
    resultContent.textContent =
      `${result.game.game_date} ${result.game.stadium}\n` +
      `최고 ${weather.max_temperature}도 / 최저 ${weather.min_temperature}도\n` +
      `강수확률 ${weather.precipitation_probability}%\n\n` +
      result.local_recommendation;
    return;
  }

  if (data.tool === "recommend_jamsil_food") {
    resultContent.textContent = (result.restaurants || [])
      .map((item) => `${item.name}\n${item.menu}\n${item.location}\n${item.reason}`)
      .join("\n\n") || "추천 결과가 없습니다.";
  }
}

async function sendMessage(message) {
  const trimmed = message.trim();
  if (!trimmed) return;

  addBubble(trimmed, "user");
  input.value = "";
  const loading = addBubble("트윈스봇이 확인하고 있어요.", "bot", "loading");

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: trimmed, history }),
    });
    const data = await response.json();
    loading.remove();
    addBubble(data.answer, "bot");
    if (data.tool === "guide_lg_twins_booking" && data.tool_result) {
      if (wantsBookingSteps(data.tool_result)) {
        renderBookingSteps(data.tool_result);
        addActionLink(data.link || data.tool_result.booking_link, "인터파크 예매 페이지 열기");
      }
      if (wantsSeatVisual(data.tool_result)) {
        renderSeatMap(pickSeatZone(data.answer, data.tool_result));
      }
    }
    history.push({ role: "user", content: trimmed });
    history.push({ role: "assistant", content: data.answer });
    toolName.textContent = TOOL_LABELS[data.tool] || "일반 답변";
    setResult(data);
  } catch (error) {
    loading.remove();
    addBubble("서버와 연결하지 못했어요. 백엔드가 실행 중인지 확인해 주세요.", "bot");
  }
}

function renderCalendar() {
  const year = cursor.getFullYear();
  const month = cursor.getMonth();
  monthLabel.textContent = `${year}.${String(month + 1).padStart(2, "0")}`;
  calendarGrid.innerHTML = "";

  const firstDay = new Date(year, month, 1);
  const lastDay = new Date(year, month + 1, 0);

  for (let i = 0; i < firstDay.getDay(); i += 1) {
    calendarGrid.appendChild(document.createElement("span"));
  }

  for (let day = 1; day <= lastDay.getDate(); day += 1) {
    const date = new Date(year, month, day);
    const key = formatDate(date);
    const button = document.createElement("button");
    button.className = "day";
    button.type = "button";
    button.textContent = String(day);

    if (gameDates.has(key)) {
      button.classList.add("has-game");
      if (key < todayKey) {
        button.classList.add("past-game");
      } else if (key === todayKey) {
        button.classList.add("today-game");
      } else {
        button.classList.add("upcoming-game");
      }
      button.title = gameDates.get(key).map((game) => `${game.game_time} ${game.opponent}`).join("\n");
      button.addEventListener("click", () => {
        selectedDate = key;
        renderCalendar();
        sendMessage(`${key} 경기 일정과 날씨에 맞는 복장 추천해줘`);
      });
    }

    if (key === todayKey) {
      button.classList.add("today");
      button.setAttribute("aria-label", `${day}일 오늘`);
    }

    if (selectedDate === key) {
      button.classList.add("selected");
    }

    calendarGrid.appendChild(button);
  }
}

async function loadCalendarDates() {
  const response = await fetch(DATES_URL);
  const data = await response.json();
  gameDates = new Map();

  for (const game of data.dates || []) {
    if (!gameDates.has(game.game_date)) {
      gameDates.set(game.game_date, []);
    }
    gameDates.get(game.game_date).push(game);
  }

  const firstUpcoming = [...gameDates.keys()].find((date) => date >= formatDate(new Date()));
  if (firstUpcoming) {
    const [year, month] = firstUpcoming.split("-").map(Number);
    cursor = new Date(year, month - 1, 1);
  }

  renderCalendar();
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(input.value);
});

prevMonth.addEventListener("click", () => {
  cursor = new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1);
  renderCalendar();
});

nextMonth.addEventListener("click", () => {
  cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
  renderCalendar();
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => sendMessage(button.dataset.prompt));
});

addBubble(
  "안녕하세요. 일정, 예매, 경기 날씨에 맞는 복장, 잠실 먹거리까지 한 번에 도와드릴게요.",
  "bot"
);
loadCalendarDates();
