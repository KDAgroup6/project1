const API_URL = "http://localhost:8000/booking-help";

const form = document.getElementById("chat-form");
const input = document.getElementById("message");
const log = document.getElementById("log");

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
      body: JSON.stringify({ message }),
    });
    const data = await response.json();
    addBubble(data.answer, "bot");
    addBookingLink(data.link);
  } catch (error) {
    addBubble("서버에 연결할 수 없습니다.", "bot");
  }
});
