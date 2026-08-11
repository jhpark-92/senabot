# MCP_SERVER 개발 환경 세팅 로그

새 워크스페이스 `~/MCP_SERVER`에서 개발 환경을 구축한 과정과 트러블슈팅 기록.

---

## 1. 폴더 생성 및 VS Code 열기

```bash
mkdir -p ~/MCP_SERVER
cd ~/MCP_SERVER
code .
```

## 2. 가상환경(venv) 생성

```bash
python3 -m venv venv
```

### ⚠️ 트러블슈팅: venv 생성 중 KeyboardInterrupt

**증상**: `python3 -m venv venv` 실행 중 pip 설치 단계에서 시간이 오래 걸려 `Ctrl+C`로 중단함.
그 결과 `venv/bin/activate` 파일이 생성되지 않은 상태로 폴더만 절반 만들어짐.

```
source /Users/jini/MCP_SERVER/venv/bin/activate
source: no such file or directory: .../venv/bin/activate
```

**원인**: venv 생성은 내부적으로 pip를 설치하는 과정(ensurepip)을 포함하는데, 이 단계가 원래 시간이 좀 걸림. 완료 전에 강제 종료하면 불완전한 상태로 남음.

**해결**: 불완전하게 생성된 venv 폴더를 삭제하고, 완료될 때까지 기다리며 재생성.

```bash
rm -rf venv
python3 -m venv venv
# 완료될 때까지 대기 (보통 10~30초)
```

**확인**:
```bash
ls venv/bin/activate   # 파일이 존재해야 정상
```

## 3. 가상환경 활성화

```bash
source venv/bin/activate
```
프롬프트 앞에 `(venv)`가 표시되면 정상 활성화된 것.

## 4. 필요 패키지 설치

```bash
pip3 install fastapi uvicorn fastmcp requests python-dotenv google-genai
```

✅ 설치 완료 확인 (`pip3 list`에서 requests, uvicorn, websockets 등 확인됨)

## 5. `.env` 파일 생성

`.env` 파일에 API 키 저장 (기존 발급받은 Gemini API 키 재사용):
```
GOOGLE_API_KEY=발급받은_키
```

## 6. `.gitignore` 설정

```bash
echo "venv/" >> .gitignore
echo ".env" >> .gitignore
```

✅ 확인 완료 (`cat .gitignore` → `venv/`, `.env` 두 줄 정상 출력)

## 7. `members.json` 작성

가상 회원 마일리지/등급 데이터 5명분 작성 완료. (회원번호, 이름, 누적 마일리지, 등급, 등급 만료일)

## 7. 환경 확인

```bash
which python3      # ~/MCP_SERVER/venv/bin/python3 나와야 정상
pip3 list          # 설치한 패키지들 확인
```

---

## 다음 단계 (진행 예정)

- [x] `members.json` — 가상 회원 마일리지/등급 데이터 작성
- [x] `main.py` — FastAPI로 회원 조회 API 구축 (직접 작성, 정상 동작 확인)
- [x] `mcp_server.py` — MCP 도구 작성 (get_member_status, get_all_members, 직접 작성)
- [x] MCP Inspector로 직접 테스트 (두 도구 모두 정상 동작 확인)
- [x] Gemini 챗봇에 연결하여 실제 대화 확인 (성공! 존재하지 않는 회원 질문 시 전체 목록까지 스스로 보여주는 것 확인)

## 트러블슈팅 기록 3~5건 (chatbot_mcp.py 관련)

### `tools=[mcp_client.session]` 방식에서 pickle 에러
**증상**: `TypeError: cannot pickle '_asyncio.Future' object`
**원인**: google-genai 최신 버전(2.17.0)이 config를 deepcopy하는 과정에서, 살아있는 비동기 MCP 세션 객체까지 복사하려다 실패. 라이브러리 자체의 알려진 호환성 이슈.
**시도한 해결책 1**: google-genai를 1.x 버전으로 다운그레이드 → 다른 에러로 바뀜 (아래)

### 스키마 변환 중 bool 에러
**증상**: `AttributeError: 'bool' object has no attribute 'items'`
**원인**: FastMCP가 생성한 도구 스키마의 `additionalProperties: false`(불리언 값)를, google-genai의 MCP→Gemini 스키마 변환 로직이 처리하지 못함. 이 역시 라이브러리 버그.
**최종 해결**: `tools=[mcp_client.session]`처럼 세션을 통째로 넘기는 방식 자체를 포기. 대신 각 MCP 도구를 **async 파이썬 함수로 감싸서** (`mcp_client.call_tool()` 호출 + `.data`로 결과 추출) `tools=[함수1, 함수2]` 형태로 넘김. 이러면 google-genai가 세션이 아닌 순수 함수만 다루므로 두 버그를 모두 우회함.

### Gemini 무료 티어 rate limit
**증상**: `429 RESOURCE_EXHAUSTED`, `Quota exceeded ... limit: 5`
**원인**: `gemini-3.6-flash` 무료 티어는 분당 5회 요청 제한. 디버깅 중 반복 실행으로 초과됨.
**해결**: 약 1분 대기 후 재시도. 테스트 시 요청 간 간격 두기.

## 최종 아키텍처

```
사람 입력 → chatbot_mcp.py (Gemini가 자연어 이해 + 도구 판단)
    → mcp_client.call_tool() → mcp_server.py (MCP 프로토콜, FastMCP)
    → main.py (FastAPI) → members.json (가상 데이터)
    → 결과 역순 전달 → Gemini가 자연어로 답변 생성 → 화면 출력
```

프로젝트 완료. 항공편 프로젝트(`~/Python`)와 동일한 구조를, 이번엔 대부분 직접 설계/구현/디버깅함.
