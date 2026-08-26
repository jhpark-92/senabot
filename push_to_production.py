"""
로컬 guide_data.json의 특정 덱 내용을, 배포된 사이트의 PUT /guide/{deck_name} API를 통해
실제 서비스에 반영하는 스크립트.

Railway Volume 특성상 git push만으로는 서비스 데이터가 갱신되지 않으므로,
"덱 수정" 기능과 동일한 정식 경로(API)를 통해 업데이트한다.
"""

import json
import requests
import getpass

SITE_URL = "https://senabot-production.up.railway.app"

# 이번에 업데이트할 덱 이름들 (update_guide.py 실행 결과에 나온 리스트를 그대로 넣으면 됨)
DECK_NAMES_TO_PUSH = ['여델칼']

def main():
    username = input("아이디: ")
    password = getpass.getpass("비밀번호: ")

    with open("guide_data.json", "r", encoding="utf-8") as f:
        guide_data = json.load(f)

    for deck_name in DECK_NAMES_TO_PUSH:
        if deck_name not in guide_data:
            print(f"[건너뜀] '{deck_name}'이 로컬 guide_data.json에 없습니다.")
            continue

        deck = guide_data[deck_name]
        payload = {
            "counter_decks": deck.get("counter_decks", []),
            "priority_note": deck.get("priority_note", ""),
            "equipment": deck.get("equipment", ""),
            "notes": deck.get("notes", ""),
            "username": username,
            "password": password,
        }

        res = requests.put(f"{SITE_URL}/guide/{deck_name}", json=payload)
        if res.ok:
            print(f"[성공] {deck_name}")
        else:
            print(f"[실패] {deck_name} - {res.status_code}: {res.text}")


if __name__ == "__main__":
    main()