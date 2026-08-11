from dotenv import load_dotenv
load_dotenv()
import os
import json
from google import genai

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

with open("guide_content.txt", "r", encoding="utf-8") as f:
    raw_text = f.read()

prompt = f"""아래는 게임 길드전 공격팀 세팅에 대한 비정형 공략 메모입니다.
이 내용을 방어덱 이름을 키(key)로 하는 JSON으로 구조화해주세요.

각 방어덱마다 다음 필드를 포함하세요:
- counter_decks: 그 방어덱을 상대할 때 쓰는 공격 조합 리스트
- priority_note: 여러 카운터 조합 중 우선순위나 승률 관련 메모
- equipment: 장비/세팅 관련 핵심 수치나 조건
- notes: 그 외 주의사항, 지는 케이스, 팁 등

JSON만 출력하고 다른 설명은 하지 마세요.

원본 내용:
{raw_text}
"""

response = client.models.generate_content(
    model="gemini-3.6-flash",
    contents=prompt,
)

# Gemini 응답에서 JSON 부분만 추출해서 저장
result_text = response.text.strip()
if result_text.startswith("```"):
    result_text = result_text.split("```")[1]
    if result_text.startswith("json"):
        result_text = result_text[4:]

guide_data = json.loads(result_text)

with open("guide_data.json", "w", encoding="utf-8") as f:
    json.dump(guide_data, f, ensure_ascii=False, indent=2)

print(f"{len(guide_data)}개 덱 정보로 구조화 완료")