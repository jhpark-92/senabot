from dotenv import load_dotenv
load_dotenv()

import os
import json
from fastmcp import Client
from google import genai
from google.genai import types

PORT = os.environ.get("PORT", "8001")
mcp_client = Client("mcp_server.py", env={**os.environ, "PORT": PORT})
gemini_client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

def load_abbreviations():
    with open("abbreviations.json", "r", encoding="utf-8") as f:
        return json.load(f)

abbreviations = load_abbreviations()

SYSTEM_INSTRUCTION = f"""당신은 게임 길드전 공격팀 세팅을 도와주는 전문가 챗봇입니다.

[답변 원칙]
사용자의 질문에 답할 때는 반드시 get_guide 도구로 가이드 데이터를 먼저 조회해서 답변하세요.
"카운터", "잡다", "패다", "이기다", "상대하다" 등은 모두 같은 의미(그 방어덱을 상대로 이기는 공격 조합)로 이해하세요.

[캐릭터 축약어 사전]
덱 이름은 아래 캐릭터 이름 축약어의 조합입니다:
{json.dumps(abbreviations, ensure_ascii=False, indent=2)}

[오(五) 글자 해석 규칙]
덱 이름에 "오"가 포함되어 있으면, 함께 나온 다른 글자를 보고 다음 규칙으로 판단하세요:
- "선", "델", "여", "칼", "란" 중 하나와 함께 나오면 → "오"는 오르카
- "라", "아", "엘", "겔", "클", "루" 중 하나와 함께 나오면 → "오"는 오공
- "린", "밀", "실", "프", "레", "연", "스", "초" 중 하나와 함께 나오면 → "오"는 오목
예를 들어 "선델오"는 선란+델론즈+오르카, "루겔오"는 루디+겔리두스+오공을 의미합니다.
그래도 애매하면 사용자에게 "오공/오르카/오목 중 어느 쪽인가요?"라고 되물어보세요.

"불확실_확인필요"에 있는 축약어(오, 엘)는 여러 캐릭터를 가리킬 수 있으니, 데이터에 있는 실제 덱 이름과 대조해서 가장 일치하는 쪽으로 판단하세요.
사용자가 캐릭터 이름을 순서 상관없이 나열하거나(예: "선란 델론즈 오르카"), 축약어로 조합해서 말하면(예: "선델오") 같은 덱을 가리키는 것으로 이해하세요.
그래도 어떤 덱인지 애매하면, 짧고 의미 없는 답변("아", "네") 대신 "혹시 OO 조합을 말씀하신 건가요?"처럼 되물어보세요.

[정정 처리]
사용자가 "이거 틀렸어", "사실은 ~야" 처럼 기존 내용을 정정하려고 하면,
add_correction 도구를 사용해 정정 내용을 저장하고, 저장했다고 알려주세요."""

async def ask(user_message: str) -> str:
    async with mcp_client:
        async def get_guide() -> dict:
            """길드전 방어덱별 카운터 조합, 장비 세팅, 주의사항이 담긴 구조화된 가이드 데이터를 조회합니다. 정정된 내용도 함께 포함됩니다."""
            result = await mcp_client.call_tool("get_guide", {})
            return result.data

        async def add_correction(wrong_info: str, correct_info: str) -> dict:
            """가이드 내용 중 잘못된 정보를 정정합니다. 사용자가 특정 내용이 틀렸다고 지적하면 이 도구를 사용하세요."""
            result = await mcp_client.call_tool(
                "add_correction",
                {"wrong_info": wrong_info, "correct_info": correct_info}
            )
            return result.data

        response = await gemini_client.aio.models.generate_content(
            model="gemini-3.6-flash",
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                tools=[get_guide, add_correction],
            ),
        )
        return response.text