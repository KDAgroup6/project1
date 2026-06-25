# LG 트윈스 잠실 먹거리 챗봇

PRD 8.4의 음식점 추천 기능만 구현한 간단한 Gradio 프로그램입니다.

## 구성

- `food.py`: 음식점 데이터, 추천 로직, Gradio 화면
- `requirements.txt`: 실행에 필요한 라이브러리

SQLite DB, 외부 API, 관리자용 DB 초기화 기능은 사용하지 않습니다.
음식점 정보는 `food.py`의 `RESTAURANTS` 리스트에서 바로 수정할 수 있습니다.

## 실행

```bash
pip install -r project1\requirements.txt
python project1\food.py
```

## 구현 기능

- 잠실야구장 내부 / 경기장 주변 선택
- 내부: 든든한 식사 / 간단한 간식 / 인기 음식
- 주변: 경기 전 / 경기 후
- 대표 메뉴, 위치·거리, 추천 이유 출력
- 간단한 키워드 질문 처리
- 처음으로 돌아가기
