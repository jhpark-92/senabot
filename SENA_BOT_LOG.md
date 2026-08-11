# Sena_Bot 개발 로그

길드전 공략 가이드 문서를 기반으로 질문에 답하고, 틀린 정보는 정정할 수 있는 챗봇 프로젝트.

---

## 프로젝트 개요

- **목적**: `guide_content.txt`(길드전 공격팀 셋팅 가이드) 내용을 바탕으로 질의응답
- **핵심 기능**: 일반 조회뿐 아니라, 사용자가 "이거 틀렸어, 사실은 ~야"라고 하면 정정 내용을 저장하고 이후 답변에 반영
- **설계 방식**: 파일 크기가 작아(3만여 자) 별도 벡터DB/RAG 없이, 원본 텍스트 전체 + 정정사항을 매 요청마다 LLM에 통째로 전달하는 방식

## 1. 폴더 및 가상환경 세팅

```bash
cd ~/Sena_Bot
python3 -m venv venv
source venv/bin/activate
```
✅ 정상 완료 (지난 프로젝트에서 겪은 중간 중단 문제 없이 한 번에 성공)

## 2. 패키지 설치

```bash
pip3 install fastapi uvicorn fastmcp requests python-dotenv "google-genai<2.0"
```
✅ 설치 완료. `google-genai`는 처음부터 1.75.0(1.x대)로 설치 — 이전 프로젝트에서 2.x대 버전이 일으켰던 pickle 에러, 스키마 변환 버그를 원천 차단하기 위함.

## 3. `.env`, `.gitignore` 설정

`.env`:
```
GOOGLE_API_KEY=기존 키 재사용
```

`.gitignore`:
```
venv/
.env
```

## 4. 지식 베이스 준비

**1차**: `길드전_공격팀_셋팅_가이드라인.xlsx` + `길드전.txt` 병합 → `guide_content.txt` (32,087자)

**2차 (업데이트)**: 추가로 `길드전_정리_노트.txt`, `길드전_강의.txt` 2개 파일을 받아 기존 내용과 함께 재구성. 총 4개 출처를 하나의 `guide_content.txt`로 통합 (56,819자).

- 출처 1: 방어덱별 공격 조합 가이드 (엑셀)
- 출처 2: 밀실스 카운터 및 기타 공략 메모
- 출처 3: 길드전 정리 노트
- 출처 4: 길드전 강의 (덱별 승률/공략 상세)

참고: 문서가 이 정도(수만 자) 규모까지는 별도 RAG(청킹+임베딩) 없이 전체를 컨텍스트로 통째 전달하는 방식으로 충분. 더 커지면 그때 RAG 도입 고려.

---

## 5. 웹 UI 구축

FastAPI에 웹 UI를 붙여서 네 가지 화면 구성:
- **챗봇 탭**: 질문/정정 대화
- **가이드 보기 탭**: 마스터-디테일 레이아웃 (왼쪽 덱 목록 검색, 오른쪽 상세 정보) — 초기엔 원본 텍스트를 그냥 나열해서 스크롤 불편했던 걸 개선
- **덱 수정 탭 (신규)**: 덱별 필드(카운터 조합/우선순위/장비/메모)를 직접 폼으로 수정, 챗봇 대화 없이 바로 수정 가능
- **정정 내역 탭**: 챗봇 대화 중 발생한 자유 형식 정정 기록

구조: `main.py`(FastAPI, 정적 파일 서빙 + API) + `chat_logic.py`(Gemini+MCP 로직 분리) + `static/index.html`(단일 페이지 UI)

## 6. 원본 텍스트 → 구조화 데이터 전환

`guide_content.txt`(원본 텍스트 그대로 이어붙인 것) 방식의 한계(가독성, "최신 정보 우선" 판단의 불안정성) 때문에 구조화된 `guide_data.json`으로 전환.

- 1차 시도: 5.6만자 전체를 한 번에 Gemini에 넣어 구조화 → 15개 항목만 추출 (누락 심함)
- 2차 시도(`restructure_v2.py`): 4개 원본 출처를 개별로 나눠 처리 후 병합 → 100개 항목으로 개선
- `main.py`, `chat_logic.py`, `mcp_server.py`, UI 전체가 `guide_data.json` 구조를 사용하도록 업데이트
- `PUT /guide/{deck_name}` 엔드포인트 추가 — 덱 수정 탭에서 특정 덱의 필드를 직접 덮어쓰기 위함

## 7. Gemini API 키 관련 트러블슈팅

**증상**: `401 UNAUTHENTICATED`, `ACCESS_TOKEN_TYPE_UNSUPPORTED`
**원인**: 2026년 6월부터 Google이 API 키 형식을 `AIzaSy...`에서 `AQ.Ab...`로 전환 중. 키 형식 자체는 정상이었고, 실제 원인은 **복사 과정에서 키 끝 글자 하나가 누락**된 것이었음 (`~/MCP_SERVER/.env`와 `diff`로 비교해서 발견).
**교훈**: 키 복사는 `cp` 명령어로 파일째 복사하는 게 오타 위험이 없어 더 안전함.

## 8. 접근 보호 추가 (배포 대비)

**목표**: 길드원 10~30명이 링크로 접속해서 함께 사용

**배포 전 고려한 위험**: 쓰기 엔드포인트(`/corrections`, `/guide/{deck}`)에 인증이 없어 외부인도 데이터 수정 가능 → 공유 비밀번호 보호 추가

**적용 내용**:
- `main.py`: `SHARED_PASSWORD` 환경변수 기반 비밀번호 검증 (`check_password()`)
- `Correction`, `DeckUpdate` 모델에 `password` 필드 추가
- UI: `localStorage`에 비밀번호 저장해서 매번 재입력 안 하도록 처리 (`getPassword()`)

**트러블슈팅**: `saveDeck()` 함수에 `password` 필드 누락 → `422 Unprocessable Content`. 브라우저 개발자도구 Network 탭에서 Request Payload를 직접 확인해서 원인 특정 (403이 아니라 422였다는 게 단서 — 인증 실패가 아니라 필드 검증 실패였음).

✅ 로컬에서 비밀번호 보호 + 덱 수정 정상 동작 확인 완료

## 다음 단계: 배포 (진행 예정)

**배포 전 남은 고려사항 2가지**:
1. Gemini 무료 티어 rate limit이 전체 사용자와 공유됨 (분당 5~15회 수준) — 30명이 몰리면 429 가능성
2. 대부분의 무료 호스팅은 파일시스템이 휘발성 → `guide_data.json`, `corrections.json` 저장 데이터가 재배포/재시작 시 날아갈 수 있음 → 영구 저장 볼륨(Volume) 필요

**할 일**:
- [ ] `requirements.txt` 작성 완료 확인 (fastapi, uvicorn, fastmcp, requests, python-dotenv, google-genai)
- [ ] GitHub에 코드 업로드 (.env, venv는 .gitignore로 제외)
- [ ] Railway 가입 및 저장소 연결, 환경변수(GOOGLE_API_KEY, SHARED_PASSWORD) 설정
- [ ] 영구 저장 볼륨 연결 (guide_data.json, corrections.json 유지용)
- [ ] 배포 후 실제 접속 테스트, 길드원들에게 링크 공유
