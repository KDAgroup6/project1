제공해주신 파이썬 코드를 바탕으로 프로젝트의 핵심 목적과 기능, 실행 방법을 명확하게 정리한 `README.md` 파일 초안입니다.

---

# ⚾ LG 트윈스 직관 도우미 챗봇 (LG Twins Game Day Chatbot)

이 프로젝트는 **FastAPI**와 **OpenAI Function Calling** 기술을 활용하여 LG 트윈스 팬들의 직관 준비를 돕는 대화형 챗봇 서버입니다. LLM(대형 언어 모델)이 실제 데이터를 기반으로 정확한 정보를 제공하도록 설계되었습니다.

---

## 🚀 핵심 기능 (Tools)

본 챗봇은 사용자의 질문 의도를 파악하여 다음 4가지 도구를 스스로 호출합니다.

* **경기 일정 조회**: LG 트윈스 공식 API와 로컬 SQLite DB를 연동하여 경기 시간, 장소, 상대팀, 승패 결과를 실시간으로 제공합니다.
* **예매 및 좌석 안내**: 인터파크 티켓 연동 링크와 함께 관람 스타일에 따른 최적의 좌석(내야/외야/응원석) 정보를 안내합니다.
* **날씨 기반 복장 추천**: Open-Meteo API를 통해 경기 당일 경기장 날씨를 조회하고, 기온과 강수확률에 맞는 옷차림 및 준비물을 추천합니다.
* **잠실 맛집 추천**: 외부 맛집은 검색 API(카카오/네이버)를 활용하고, 경기장 내부 매점은 직접 선별한 고정 목록을 사용하여 정확한 정보를 제공합니다.

---

## 🛠 주요 기술 포인트

1. **환각(Hallucination) 방지**: 모든 정보는 실제 API나 검증된 데이터베이스에서 가져옵니다.
2. **안전망(Fallback) 로직**: OpenAI API 키가 없거나 호출에 실패하더라도, 내부 키워드 규칙을 통해 경기 일정 및 주요 정보를 안내할 수 있도록 설계되었습니다.
3. **JSON Schema 정의**: 모델이 도구 호출 시 혼동하지 않도록 명확한 파라미터 규격을 정의했습니다.

---

## ⚙️ 환경 설정 및 실행 방법

### 1. 환경 변수 설정

`backend/.env` 파일을 생성하고 다음 환경 변수를 입력하세요.

```env
OPENAI_API_KEY=your_openai_api_key
OPENAI_DEFAULT_MODEL=gpt-4o-mini
KAKAO_REST_API_KEY=your_kakao_api_key
NAVER_CLIENT_ID=your_naver_client_id
NAVER_CLIENT_SECRET=your_naver_client_secret

```

### 2. 실행 명령어

의존성 라이브러리를 설치한 후 서버를 실행합니다.

```bash
# 의존성 설치
pip install fastapi uvicorn openai python-dotenv

# 서버 실행
uvicorn backend.main:app --reload

```

---

## 📂 프로젝트 구조

```text
project_root/
├── backend/          # FastAPI 서버 및 비즈니스 로직
│   └── main.py       # 챗봇 핵심 서버 코드
├── data/             # 경기 일정 SQLite DB
└── frontend/         # HTML/CSS/JS 웹 화면

```

---

## 📝 라이선스 및 참고

* 본 챗봇은 LG 트윈스 공식 데이터를 활용합니다.
* 날씨 정보 제공: [Open-Meteo](https://open-meteo.com/)
* 지도 검색 제공: 카카오 로컬 API, 네이버 로컬 API
