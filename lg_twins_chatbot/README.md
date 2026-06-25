# 트윈스봇

LG 트윈스 직관 준비를 돕는 통합 챗봇입니다.

## 포함 기능

- `get_lg_twins_schedule`: LG 트윈스 경기 일정 조회
- `guide_lg_twins_booking`: 경기 예매 방법과 좌석 선택 안내
- `recommend_outfit_by_weather`: 선택 경기일의 날씨 기반 복장 추천
- `recommend_jamsil_food`: 잠실야구장 내/외부 먹거리 추천

## 실행 방법

가장 쉬운 방법은 아래 파일을 더블클릭하는 것입니다.

```text
C:\group6\lg_twins_chatbot\run_twinsbot.bat
```

처음 실행할 때 필요한 패키지를 설치한 뒤 `http://127.0.0.1:8000`을 자동으로 엽니다.

## 발표용으로 인터넷 배포하기

발표 때 공유 링크가 필요하면 Render 같은 웹 배포 서비스를 쓰면 됩니다.

추천 순서:

1. 이 폴더를 GitHub 저장소에 올립니다.
2. Render에서 `New Web Service`를 만듭니다.
3. Root Directory를 `lg_twins_chatbot`으로 설정합니다.
4. Build Command:

```text
pip install -r backend/requirements.txt
```

5. Start Command:

```text
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

6. Environment Variables에 아래 값을 추가합니다.

```text
OPENAI_API_KEY=발급받은 키
OPENAI_DEFAULT_MODEL=gpt-4o-mini
```

배포가 끝나면 Render가 만들어준 `https://...onrender.com` 주소를 발표 때 공유하면 됩니다.

중요:

- `.env` 파일은 GitHub에 올리지 마세요. 키는 배포 서비스의 Environment Variables에만 넣습니다.
- 무료 서버는 처음 접속할 때 잠깐 느릴 수 있습니다.
- OpenAI API를 쓰므로 발표 장소 인터넷 연결이 필요합니다.

## 같은 네트워크에서 같이 접속하기

한 사람의 PC에서 아래 파일을 실행합니다.

```text
C:\group6\lg_twins_chatbot\run_twinsbot_lan.bat
```

실행 창에 표시되는 `http://내_IP:8000` 주소를 같은 와이파이/네트워크에 있는 사람들에게 공유하면 됩니다.

주의:

- 서버를 켠 PC의 창을 닫으면 다른 사람도 접속할 수 없습니다.
- 다른 사람 PC에서는 `file:///.../index.html`을 열면 안 되고, 반드시 `http://내_IP:8000` 주소로 접속해야 합니다.
- Windows 방화벽 알림이 뜨면 Python 또는 Uvicorn 접속을 허용해야 합니다.
- 학교/회사 네트워크처럼 기기 간 접속이 막힌 환경에서는 같은 와이파이여도 접속이 안 될 수 있습니다.

수동 실행이 필요하면 아래 순서를 사용합니다.

```powershell
cd C:\group6\lg_twins_chatbot
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
copy .\backend\.env.example .\backend\.env
```

`.env`에 `OPENAI_API_KEY`를 입력한 뒤 실행합니다.

```powershell
.\.venv\Scripts\uvicorn.exe backend.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 `http://127.0.0.1:8000`을 열면 됩니다.

OpenAI 키가 없거나 호출에 실패해도 기본 분류 방식으로 일정, 예매, 복장, 먹거리 답변을 이어가도록 구성되어 있습니다.
