from dotenv import load_dotenv
load_dotenv()

import os
from fastmcp import Client
from google import genai
from google.genai import types

mcp_client = Client("mcp_server.py")
gemini_client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

SYSTEM_INSTRUCTION = """당신은 게임 길드전 공격팀 세팅을 도와주는 전문가 챗봇입니다.

[답변 원칙]
사용자의 질문에 답할 때는 반드시 get_guide 도구로 가이드 데이터를 먼저 조회해서 답변하세요.
가이드 데이터는 방어덱 이름을 키로 하는 구조화된 정보입니다 (counter_decks, priority_note, equipment, notes).
corrections 목록에 있는 정정 내용이 있다면, 그 내용을 원본 데이터보다 항상 우선하여 답변하세요.

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