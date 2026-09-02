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


if __name__ == "__main__":
    mcp.run()