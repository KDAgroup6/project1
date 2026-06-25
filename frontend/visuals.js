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
