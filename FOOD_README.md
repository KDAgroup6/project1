# LG 트윈스 잠실 먹거리 챗봇

PRD 8.4의 음식점 추천 기능만 구현한 간단한 Gradio 프로그램입니다.

## 구성

- `food.py`: 음식점 데이터, 추천 로직, Gradio 화면
- `requirements.txt`: 실행에 필요한 라이브러리

SQLite DB, 외부 API, 관리자용 DB 초기화 기능은 사용하지 않습니다.
음식점 정보는 `food.py`의 `INSIDE_RESTAURANTS`(야구장 내부) /
`OUTSIDE_RESTAURANTS`(주변 맛집) 리스트에서 바로 수정할 수 있습니다.

## 실행

```bash
pip install -r project1\requirements.txt
python project1\food.py
```

## 구현 기능

- 잠실야구장 내부 / 경기장 주변 선택
- 내부: 든든한 식사 / 간단한 간식 / 인기 음식
  - 실제 입점 매장 기준으로 **대표 메뉴 · 대략적인 가격 · 위치 · 특징**을 안내
- 주변: 경기 전 / 경기 후 (잠실새내역 도보권 위주)
  - 식당 이름과 "🗺️ 네이버 지도에서 보기"를 누르면 해당 식당의
    **네이버 지도 검색 페이지가 새 탭(팝업)으로 바로 열림**
- 간단한 키워드 질문 처리
- 처음으로 돌아가기

## 네이버 지도 링크 동작 방식

별도의 API 키 없이 네이버 지도 공개 검색 URL을 사용합니다.

```
https://map.naver.com/p/search/{검색어}
```

`food.py`의 `naver_map_link()` 가 식당의 `naver_query` 값을 URL 인코딩해
위 형식의 링크를 만들고, Gradio Chatbot의 마크다운 링크로 출력합니다.
사용자가 링크를 클릭하면 새 탭에서 해당 식당의 네이버 지도 페이지로 이동합니다.

> 참고 자료: [awesome-mcp-korea](https://github.com/darjeeling/awesome-mcp-korea),
> [LangChain + MCP 연동 예시](https://digitalbourgeois.tistory.com/1017)
