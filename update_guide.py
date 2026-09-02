from dotenv import load_dotenv
load_dotenv()
import os
import json
import time
import shutil
import re
from google import genai

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

UPDATES_DIR = "data"
PROCESSED_DIR = os.path.join(UPDATES_DIR, "processed")

SEPARATOR = "-------------------------------------------------------------------------------------"

# ===== 완전히 새로운 덱일 때 쓰는 프롬프트 (기존과 동일) =====
NEW_DECK_PROMPT = """아래는 게임 길드전 공격팀 세팅에 대한 비정형 공략 메모입니다.
이 텍스트 하나에는 "{deck_name}" 방어덱 하나에 대한 정보만 담겨 있습니다.

이 내용을 다음 JSON 형식으로 정확히 구조화해주세요:
{{
  "counter_decks": ["카운터 조합1", "카운터 조합2", ...],
  "priority_note": "우선순위 관련 전체 내용을 하나의 문자열로 정리",
  "equipment": "장비 세팅 관련 전체 내용을 하나의 문자열로 정리 (각 조합별로 구분해서)",
  "notes": "메모 섹션의 전체 내용을 하나의 문자열로 정리 (스킬순서, 속공, 배치, TIP 모두 포함)"
}}

중요한 규칙:
- 원문의 내용을 요약하거나 생략하지 말고, 세부 수치와 조건까지 최대한 그대로 담아주세요.
- JSON만 출력하고 다른 설명은 하지 마세요.

원본 내용:
{content}
"""

# ===== 기존 덱에 새 정보를 "병합"할 때 쓰는 프롬프트 =====
MERGE_DECK_PROMPT = """"{deck_name}" 방어덱에 대한 기존 공략 정보와, 새로 추가된 메모가 있습니다.
이 둘을 하나로 병합해서 최신 상태로 정리해주세요.

[병합 규칙]
1. counter_decks(카운터 조합 목록): 기존 목록에 새 조합이 있으면 그대로 추가하세요.
   이미 있던 조합 이름(예: "선발클")에 대한 설명이 새 메모에도 나오면, 새 설명으로 그 조합의 내용을 업데이트하세요.
   기존에 있었지만 새 메모에서 언급 안 된 조합은 그대로 유지하세요 (삭제하지 마세요).
2. priority_note, equipment, notes: 기존 내용과 새 내용에 겹치는 부분이 있으면 자연스럽게 하나로 합치고,
   새로운 내용이면 기존 내용 뒤에 이어붙이세요. 이미 있던 내용을 임의로 삭제하지 마세요.
3. 절대 기존 정보를 요약하거나 생략하지 마세요. 병합 후에도 세부 수치와 조건이 다 남아있어야 합니다.

다음 JSON 형식으로만 출력하세요. 다른 설명은 하지 마세요:
{{
  "counter_decks": ["조합1", "조합2", ...],
  "priority_note": "...",
  "equipment": "...",
  "notes": "..."
}}

[기존 공략 정보]
{existing_json}

[새로 추가된 메모]
{new_content}
"""


def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def strip_parens(name):
    """괄호와 그 안 내용을 제거 (예: '동윤연(동영 윤건 연희)' -> '동윤연')"""
    return re.sub(r'\(.*?\)', '', name).strip()


def normalize(name):
    """괄호를 먼저 제거하고, 남은 글자를 정렬해서 반환.
    -> 순서만 다른 이름(연동윤/윤동연)과, 괄호 부연설명이 붙은 이름(동윤연(동영 윤건 연희))을
       모두 같은 덱으로 인식하기 위함"""
    core = strip_parens(name)
    return "".join(sorted(core))


def find_existing_key(deck_name, guide_data):
    """
    guide_data 안에서 deck_name과 같은 덱을 찾는다.
    1순위: 완전히 같은 이름
    2순위: 글자 구성이 같은 이름(순서만 다름, 예: 연동윤 vs 윤동연)
    없으면 None 반환 (완전히 새로운 덱)
    """
    if deck_name in guide_data:
        return deck_name

    target = normalize(deck_name)
    for existing_name in guide_data.keys():
        if normalize(existing_name) == target:
            return existing_name
    return None


def structure_new_deck(deck_name, content):
    print(f"  [{deck_name}] 신규 덱으로 구조화 중... ({len(content)}자)")
    prompt = NEW_DECK_PROMPT.format(deck_name=deck_name, content=content)
    response = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
    return extract_json(response.text)


def merge_deck(deck_name, existing_data, new_content):
    print(f"  [{deck_name}] 기존 정보와 병합 중... ({len(new_content)}자 추가)")
    prompt = MERGE_DECK_PROMPT.format(
        deck_name=deck_name,
        existing_json=json.dumps(existing_data, ensure_ascii=False, indent=2),
        new_content=new_content,
    )
    response = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
    return extract_json(response.text)


def process_file(filepath, guide_data):
    """파일 하나를 읽어서 덱별로 나누고, 신규는 새로 구조화 / 기존은 병합"""
    with open(filepath, "r", encoding="utf-8") as f:
        full_text = f.read()

    blocks = full_text.split(SEPARATOR)
    blocks = [b.strip() for b in blocks if b.strip()]

    updated_decks = []
    for block in blocks:
        lines = block.split("\n", 1)
        deck_name = lines[0].strip()
        content = lines[1].strip() if len(lines) > 1 else ""
        if not content:
            continue

        matched_key = find_existing_key(deck_name, guide_data)
        if matched_key:
            if matched_key != deck_name:
                print(f"  [{deck_name}] -> 기존 덱 '{matched_key}'와 같은 조합으로 인식, 그 이름으로 병합합니다.")
            # 기존 키(원래 이름)를 그대로 유지한 채 내용만 병합
            guide_data[matched_key] = merge_deck(matched_key, guide_data[matched_key], content)
            updated_decks.append(matched_key)
        else:
            # 완전히 새로운 덱 -> 새로 구조화
            guide_data[deck_name] = structure_new_deck(deck_name, content)
            updated_decks.append(deck_name)
        time.sleep(2)  # rate limit 방지

    return updated_decks


def main():
    os.makedirs(UPDATES_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    target_files = [
        f for f in os.listdir(UPDATES_DIR)
        if f.endswith(".txt") and os.path.isfile(os.path.join(UPDATES_DIR, f))
    ]

    if not target_files:
        print(f"'{UPDATES_DIR}' 폴더에 처리할 .txt 파일이 없습니다.")
        return

    with open("guide_data.json", "r", encoding="utf-8") as f:
        guide_data = json.load(f)

    all_updated = []
    for filename in target_files:
        filepath = os.path.join(UPDATES_DIR, filename)
        print(f"\n=== {filename} 처리 시작 ===")
        updated_decks = process_file(filepath, guide_data)
        all_updated.extend(updated_decks)

        shutil.move(filepath, os.path.join(PROCESSED_DIR, filename))
        print(f"=== {filename} 처리 완료, processed로 이동 ===")

    with open("guide_data.json", "w", encoding="utf-8") as f:
        json.dump(guide_data, f, ensure_ascii=False, indent=2)

    print(f"\n총 {len(all_updated)}개 덱 처리 완료: {all_updated}")


if __name__ == "__main__":
    main()