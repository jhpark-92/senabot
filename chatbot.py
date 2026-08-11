from dotenv import load_dotenv
import os
import asyncio
from fastmcp import Client
from google import genai
from google.genai import types

load_dotenv()

mcp_client = Client("mcp_server.py")
gemini_client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

SYSTEM_INSTRUCTION = """당신은 게임 길드전 공격팀 세팅을 도와주는 전문가 챗봇입니다.
사용자의 질문에 답할 때는 반드시 get_guide 도구로 가이드 내용을 먼저 조회해서 답변하세요.
사용자가 "이거 틀렸어", "사실은 ~야" 처럼 기존 내용을 정정하려고 하면,
add_correction 도구를 사용해 정정 내용을 저장하고, 저장했다고 알려주세요."""


async def chat(user_message):
    async with mcp_client:
        async def get_guide() -> dict:
            """길드전 공격팀 셋팅 가이드 전체 내용을 조회합니다. 정정된 내용이 있으면 함께 포함됩니다."""
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


async def main():
    print("길드전 가이드 챗봇입니다. 종료하려면 'exit' 입력하세요.\n")
    while True:
        user_input = input("나: ")
        if user_input.lower() == "exit":
            print("종료합니다.")
            break
        answer = await chat(user_input)
        print(f"챗봇: {answer}\n")


if __name__ == "__main__":
    asyncio.run(main())