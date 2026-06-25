# LG 트윈스 잠실 먹거리 챗봇

PRD 8.4의 음식점 추천 기능만 구현한 간단한 Gradio 프로그램입니다.

## 구성

- `food.py`: 음식점 데이터, 추천 로직, Gradio 화면
- `requirements.txt`: 실행에 필요한 라이브러리

야구장 내부 먹거리 정보는 `food.py`의 `INSIDE_RESTAURANTS` 리스트에서 바로 수정할 수 있습니다.
**주변 맛집은 네이버 지역검색 API로 실시간 조회**하며, API 키가 없으면 내장
`OUTSIDE_RESTAURANTS` 데이터로 자동 대체되어 키 없이도 실행됩니다.

## 실행

```bash
pip install -r project1\requirements.txt

# (선택) 주변 맛집 실시간 검색을 쓰려면 네이버 API 키 설정
copy project1\.env.example project1\.env   # 그리고 .env 에 키 입력

python project1\food.py
```

### 네이버 API 키 설정 (주변 맛집 실시간 검색)

[네이버 개발자센터](https://developers.naver.com)에서 "검색" API를 등록하고
발급받은 키를 `project1\.env` 에 입력합니다. (`.env` 는 깃에 커밋되지 않습니다)

```
NAVER_CLIENT_ID=발급받은_클라이언트_ID
NAVER_CLIENT_SECRET=발급받은_시크릿
```

키가 없으면 내장 맛집 데이터로 동작하므로 프로그램은 그대로 실행됩니다.

## 구현 기능

- 잠실야구장 내부 / 경기장 주변 선택
- 내부: 든든한 식사 / 간단한 간식 / 인기 음식
  - 실제 입점 매장 기준으로 **대표 메뉴 · 대략적인 가격 · 위치 · 특징**을 안내
- 주변: 경기 전 / 경기 후 (잠실새내역 도보권 위주)
  - **네이버 지역검색 API**로 실시간 맛집을 검색해 분류·주소·홈페이지를 안내
  - 식당 이름과 "🗺️ 네이버 지도에서 보기"를 누르면 해당 식당의
    **네이버 지도 검색 페이지가 새 탭(팝업)으로 바로 열림**
- 간단한 키워드 질문 처리
- 처음으로 돌아가기

## 네이버 연동 동작 방식

**① 주변 맛집 검색 — 네이버 지역검색 API**

`food.py`의 `search_naver_local()` 이 아래 API를 호출해 실제 식당 목록을 받아옵니다.

```
GET https://openapi.naver.com/v1/search/local.json?query={검색어}
    Headers: X-Naver-Client-Id, X-Naver-Client-Secret
```

방문 시점(경기 전/후)에 따라 검색어를 바꿔 호출하며,
키가 없거나 호출에 실패하면 내장 `OUTSIDE_RESTAURANTS` 데이터로 자동 대체됩니다.

**② 지도 이동 링크 — 네이버 지도 공개 검색 URL**

```
https://map.naver.com/p/search/{검색어}
```

`naver_map_link()` 가 식당 이름을 URL 인코딩해 위 링크를 만들고,
Gradio Chatbot의 마크다운 링크로 출력합니다. 클릭하면 새 탭에서
해당 식당의 네이버 지도 페이지로 이동합니다.

> 참고 자료: [awesome-mcp-korea](https://github.com/darjeeling/awesome-mcp-korea),
> [LangChain + MCP 연동 예시](https://digitalbourgeois.tistory.com/1017)
