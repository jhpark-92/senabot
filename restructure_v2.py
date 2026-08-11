from dotenv import load_dotenv
load_dotenv()
import os
import json
import time
from google import genai

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

PROMPT_TEMPLATE = """아래는 게임 길드전 공격팀 세팅에 대한 비정형 공략 메모의 일부입니다.
이 내용에 언급된 "모든" 방어덱/조합 이름을 하나도 빠짐없이 JSON으로 구조화해주세요.

중요한 규칙:
- 비슷하게 들리는 이름이라도 절대 하나로 합치지 마세요. 예를 들어 여클칼, 여오칼, 여델칼은 서로 다른 별개의 항목입니다.
- 아주 짧게 한두 줄만 언급된 조합이라도 빠뜨리지 말고 포함하세요.
- 방어덱 이름을 키(key)로 하고, 각 항목은 다음 필드를 포함하세요:
  - counter_decks: 그 방어덱을 상대할 때 쓰는 공격 조합 리스트
  - priority_note: 우선순위나 승률 관련 메모 (없으면 빈 문자열)
  - equipment: 장비/세팅 관련 핵심 수치나 조건 (없으면 빈 문자열)
  - notes: 그 외 주의사항, 지는 케이스, 팁 등 (없으면 빈 문자열)

JSON만 출력하고 다른 설명은 하지 마세요.

원본 내용:
{content}
"""

def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def structure_source(name, content):
    print(f"[{name}] 처리 중... ({len(content)}자)")
    prompt = PROMPT_TEMPLATE.format(content=content)
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )
    data = extract_json(response.text)
    print(f"[{name}] {len(data)}개 항목 추출 완료")
    return data


# guide_content.txt 안에서 출처별로 나눠져 있으니, 구분자로 분리
sources = {}
with open("guide_content.txt", "r", encoding="utf-8") as f:
    full_text = f.read()

parts = full_text.split("## 출처")
for part in parts[1:]:  # 첫 조각은 헤더라 스킵
    header_end = part.find("\n")
    source_name = part[:header_end].strip()
    source_content = part[header_end:].strip()
    sources[source_name] = source_content

# 출처별로 구조화 후 병합
merged = {}
for name, content in sources.items():
    if not content:
        continue
    data = structure_source(name, content)
    for deck_name, deck_info in data.items():
        if deck_name in merged:
            # 이미 있는 덱이면 정보를 이어붙임 (덮어쓰지 않음)
            existing = merged[deck_name]
            existing["counter_decks"] = list(set(existing.get("counter_decks", []) + deck_info.get("counter_decks", [])))
            for field in ["priority_note", "equipment", "notes"]:
                if deck_info.get(field):
                    existing[field] = (existing.get(field, "") + " / " + deck_info[field]).strip(" /")
        else:
            merged[deck_name] = deck_info
    time.sleep(2)  # rate limit 방지

with open("guide_data.json", "w", encoding="utf-8") as f:
    json.dump(merged, f, ensure_ascii=False, indent=2)

print(f"\n최종 {len(merged)}개 덱 정보로 구조화 완료")