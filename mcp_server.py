# mcp_server.py
import os
from fastmcp import FastMCP
import requests

mcp = FastMCP("Guide Tools")

# Railway가 지정하는 포트를 그대로 사용 (없으면 로컬 기본값 8001)
PORT = os.environ.get("PORT", "8001")
FASTAPI_BASE_URL = f"http://127.0.0.1:{PORT}"


@mcp.tool()
def get_guide() -> dict:
    """길드전 방어덱별 카운터 조합, 장비 세팅, 주의사항이 담긴 구조화된 가이드 데이터를 조회합니다. 정정된 내용이 있으면 함께 포함됩니다."""
    response = requests.get(f"{FASTAPI_BASE_URL}/guide")
    return response.json()


@mcp.tool()
def add_correction(wrong_info: str, correct_info: str) -> dict:
    """가이드 내용 중 잘못된 정보를 정정합니다. 사용자가 특정 내용이 틀렸다고 지적하면 이 도구를 사용하세요."""
    response = requests.post(
        f"{FASTAPI_BASE_URL}/corrections",
        json={"wrong_info": wrong_info, "correct_info": correct_info}
    )
    return response.json()


if __name__ == "__main__":
    mcp.run()