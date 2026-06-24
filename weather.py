from fastapi import FastAPI

app = FastAPI()


@app.get("/weather/")
def get_weather(date: str, temp: int, rain: bool = False):
    if rain:
        return {
            "date": date,
            "weather": "비 예보",
            "clothes": "젖어도 괜찮은 옷과 신발",
            "items": ["우비", "작은 수건", "비닐봉지"],
            "message": "비가 오더라도 경기 취소 여부는 공식 공지를 확인해야 해요."
        }

    if temp >= 28:
        weather = "더워요"
        clothes = "반팔, 통풍이 잘되는 옷"
        items = ["모자", "물", "휴대용 선풍기"]
    elif temp >= 20:
        weather = "선선해요"
        clothes = "반팔 또는 얇은 긴팔"
        items = ["얇은 겉옷", "물"]
    elif temp >= 15:
        weather = "쌀쌀해요"
        clothes = "긴팔, 바람막이"
        items = ["얇은 담요"]
    else:
        weather = "추워요"
        clothes = "두꺼운 겉옷"
        items = ["담요", "핫팩"]

    return {
        "date": date,
        "temperature": temp,
        "weather": weather,
        "clothes": clothes,
        "items": items,
        "message": f"{date} 관람에는 {clothes}을 추천해요."
    }