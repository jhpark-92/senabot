from dotenv import load_dotenv
load_dotenv()
import os
import json
import time
import shutil
from google import genai

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

UPDATES_DIR = "data"
PROCESSED_DIR = os.path.join(UPDATES_DIR, "processed")

PROMPT_TEMPLATE = """아래는 게임 길드전 공격팀 세팅에 대한 비정형 공략 메모입니다.
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

SEPARATOR = "-------------------------------------------------------------------------------------"


def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def structure_deck(deck_name, content):
    print(f"  [{deck_name}] 처리 중... ({len(content)}자)")
    prompt = PROMPT_TEMPLATE.format(deck_name=deck_name, content=content)
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )
    data = extract_json(response.text)
    print(f"  [{deck_name}] 구조화 완료")
    return data


def process_file(filepath, guide_data):
    """파일 하나를 읽어서 덱별로 나누고, 구조화된 결과를 guide_data에 반영"""
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
        guide_data[deck_name] = structure_deck(deck_name, content)
        updated_decks.append(deck_name)
        time.sleep(2)  # rate limit 방지

    return updated_decks


def main():
    os.makedirs(UPDATES_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    # guide_updates 폴더 바로 아래에 있는 .txt 파일만 대상 (processed 폴더는 제외)
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

        # 처리 끝난 파일은 processed 폴더로 이동 (중복 처리 방지)
        shutil.move(filepath, os.path.join(PROCESSED_DIR, filename))
        print(f"=== {filename} 처리 완료, processed로 이동 ===")

    with open("guide_data.json", "w", encoding="utf-8") as f:
        json.dump(guide_data, f, ensure_ascii=False, indent=2)

    print(f"\n총 {len(all_updated)}개 덱 업데이트 완료: {all_updated}")


if __name__ == "__main__":
    main()