"""
세나봇(길드전 가이드 챗봇) 백엔드 서버

주요 기능:
1. 정적 파일(index.html) 제공
2. 가이드 데이터 조회/수정 + 수정 이력 기록
3. 챗봇 대화 (Gemini + MCP 연동은 chat_logic.py에서 처리)
4. 회원가입 / 로그인 / 관리자 승인
5. 관리자용 회원 관리 (전체 조회, 삭제)
6. 공유 메모장
7. 레이드 공략 (강림 / 파괴신 / 돌발레이드)
8. Railway Volume(영구 저장소) 대응
"""

import os
import json
import shutil
import hashlib
import secrets
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from chat_logic import ask

app = FastAPI()


# =========================================================
# 영구 저장 경로 설정 (Railway Volume 대응)
#
# 로컬 개발 환경: DATA_DIR 환경변수가 없으므로 현재 폴더(".")를 그대로 사용
# 배포 환경(Railway): DATA_DIR=/data 로 설정해서, 재배포해도 안 사라지는
#                      Volume 경로에 사용자 데이터를 저장
# =========================================================

DATA_DIR = os.environ.get("DATA_DIR", ".")


def path(filename: str) -> str:
    """데이터 파일명을 실제 저장 경로(DATA_DIR 기준)로 변환"""
    return os.path.join(DATA_DIR, filename)


def ensure_data_files():
    """
    서버 시작 시 1회 실행.
    Volume이 비어있는 첫 배포라면, git에 커밋되어 있던 루트의 초기 데이터를
    Volume 경로로 복사해서 채워준다. 이미 파일이 있으면 건드리지 않는다.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    defaults = {
        "guide_data.json": {},
        "deck_history.json": [],
        "users.json": {},
        "memo.json": {"content": ""},
        "raid_data.json": {
            "강림": {
                "type": "list",
                "bosses": {"태오": "", "카일": "", "연희": "", "카르마": ""},
            },
            "파괴신": {
                "type": "single",
                "content": "",
            },
            "돌발레이드": {
                "type": "list",
                "bosses": {"칼리스트라": "", "아스트레아": "", "레오니드": ""},
            },
        },
    }
    for filename, empty_value in defaults.items():
        dest = path(filename)
        if not os.path.exists(dest):
            if os.path.exists(filename):
                # 루트에 기존 파일(git으로 배포된 초기 데이터)이 있으면 그대로 복사
                shutil.copy(filename, dest)
            else:
                # 아무 데이터도 없으면 빈 값으로 새로 생성
                with open(dest, "w", encoding="utf-8") as f:
                    json.dump(empty_value, f, ensure_ascii=False, indent=2)


ensure_data_files()


# =========================================================
# 비밀번호 관련 유틸리티
# =========================================================

# 덱 수정 / 메모장 / 레이드 저장 등에 쓰이는 "공유 비밀번호" (길드원 전체가 같이 사용)
SHARED_PASSWORD = os.environ.get("SHARED_PASSWORD", "changeme")
# 회원 승인/관리 기능에 쓰이는 "관리자 비밀번호"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme_admin")


def check_password(password: str):
    """공유 비밀번호 검증. 틀리면 403 에러를 발생시킴."""
    if password != SHARED_PASSWORD:
        raise HTTPException(status_code=403, detail="비밀번호가 올바르지 않습니다.")


def hash_password(password: str, salt: str = None):
    """
    비밀번호를 평문으로 저장하지 않기 위한 해시 처리.
    salt(솔트)를 랜덤하게 생성해서 같은 비밀번호라도 저장값이 서로 다르게 만든다.
    """
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
    return hashed, salt


def verify_password_hash(password: str, salt: str, hashed: str) -> bool:
    """로그인 시 입력한 비밀번호가 저장된 해시와 일치하는지 확인"""
    check, _ = hash_password(password, salt)
    return check == hashed


# =========================================================
# 가이드 데이터 (guide_data.json) — 덱별 카운터 조합 정보
# =========================================================

def load_guide_data():
    with open(path("guide_data.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def save_guide_data(data):
    with open(path("guide_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================================================
# 덱 수정 이력 (deck_history.json) — "정정 내역" 탭에 표시됨
# 챗봇 대화 중 정정이 아니라, "덱 수정" 탭에서 직접 편집한 기록만 남김
# =========================================================

def load_deck_history():
    try:
        with open(path("deck_history.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def save_deck_history(history):
    with open(path("deck_history.json"), "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# =========================================================
# 회원 정보 (users.json)
# 구조: { "아이디": {"hashed": ..., "salt": ..., "approved": true/false} }
# =========================================================

def load_users():
    with open(path("users.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(users):
    with open(path("users.json"), "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


# =========================================================
# 공유 메모장 (memo.json) — 관리자가 수정할 내용을 임시로 적어두는 공간
# =========================================================

def load_memo():
    try:
        with open(path("memo.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"content": ""}


def save_memo(data):
    with open(path("memo.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================================================
# 레이드 공략 (raid_data.json) — 강림 / 파괴신 / 돌발레이드
#
# 구조 예시:
# {
#   "강림": {"type": "list", "bosses": {"태오": "내용...", "카일": "", ...}},
#   "파괴신": {"type": "single", "content": "내용..."},
#   "돌발레이드": {"type": "list", "bosses": {"칼리스트라": "", ...}}
# }
#
# type이 "list"면 보스별로 따로 관리, "single"이면 카테고리 전체가 텍스트 하나
# =========================================================

def load_raid_data():
    with open(path("raid_data.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def save_raid_data(data):
    with open(path("raid_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================================================
# 요청/응답 형태 정의 (Pydantic 모델)
# =========================================================

class ChatRequest(BaseModel):
    message: str


class DeckUpdate(BaseModel):
    counter_decks: list[str]
    priority_note: str = ""
    equipment: str = ""
    notes: str = ""
    password: str  # 공유 비밀번호 (덱 수정 권한 확인용)


class PasswordCheck(BaseModel):
    password: str


class SignupRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class ApproveRequest(BaseModel):
    username: str
    admin_password: str


class RevokeRequest(BaseModel):
    username: str
    admin_password: str


class MemoUpdate(BaseModel):
    content: str
    password: str


class RaidUpdate(BaseModel):
    boss: str | None = None   # "list" 타입 카테고리일 때만 사용 (예: "태오")
    content: str
    password: str


# =========================================================
# 정적 파일 / 메인 페이지
# =========================================================

@app.get("/")
def read_index():
    """루트 접속 시 프론트엔드(index.html) 반환"""
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")


# =========================================================
# 가이드 조회 / 수정
# =========================================================

@app.get("/guide")
def get_guide():
    """전체 가이드 데이터(덱별 카운터 정보)를 반환. 인증 불필요 (조회는 누구나 가능)."""
    guide_data = load_guide_data()
    return {"guide_data": guide_data}


@app.put("/guide/{deck_name}")
def update_deck(deck_name: str, update: DeckUpdate):
    """
    특정 덱 하나의 정보를 통째로 덮어씀.
    수정 전/후 내용을 deck_history.json에 기록해서 "정정 내역" 탭에서 확인 가능하게 함.
    """
    check_password(update.password)

    guide_data = load_guide_data()
    before = guide_data.get(deck_name, {})

    after = {
        "counter_decks": update.counter_decks,
        "priority_note": update.priority_note,
        "equipment": update.equipment,
        "notes": update.notes,
    }
    guide_data[deck_name] = after
    save_guide_data(guide_data)

    # 수정 이력 기록 (변경 전/후 내용과 시각)
    history = load_deck_history()
    history.append({
        "deck_name": deck_name,
        "before": before,
        "after": after,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    save_deck_history(history)

    return {"message": f"{deck_name} 정보가 수정되었습니다."}


# =========================================================
# 수정 이력 조회 ("정정 내역" 탭)
# =========================================================

@app.get("/corrections")
def get_corrections_list():
    """덱 수정 이력을 최신순으로 반환"""
    history = load_deck_history()
    return list(reversed(history))


# =========================================================
# 공유 메모장
# =========================================================

@app.get("/memo")
def get_memo():
    return load_memo()


@app.put("/memo")
def update_memo(body: MemoUpdate):
    check_password(body.password)
    save_memo({"content": body.content})
    return {"message": "메모가 저장되었습니다."}


# =========================================================
# 레이드 공략 (강림 / 파괴신 / 돌발레이드)
# =========================================================

@app.get("/raid")
def get_raid_data():
    """레이드 공략 데이터 전체 반환 (강림/파괴신/돌발레이드)"""
    return load_raid_data()


@app.put("/raid/{category}")
def update_raid(category: str, update: RaidUpdate):
    """
    특정 카테고리(강림/파괴신/돌발레이드)의 공략 내용을 수정.
    카테고리 type이 "list"면 update.boss로 어떤 보스인지 지정해야 하고,
    "single"이면 boss 없이 content만 전체 교체한다.
    """
    check_password(update.password)
    raid_data = load_raid_data()

    if category not in raid_data:
        raise HTTPException(status_code=404, detail="존재하지 않는 카테고리입니다.")

    entry = raid_data[category]
    if entry["type"] == "single":
        entry["content"] = update.content
    else:  # "list" 타입 (보스별 관리)
        if not update.boss or update.boss not in entry["bosses"]:
            raise HTTPException(status_code=400, detail="존재하지 않는 보스입니다.")
        entry["bosses"][update.boss] = update.content

    save_raid_data(raid_data)
    return {"message": "저장되었습니다."}


# =========================================================
# 챗봇 대화
# =========================================================

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    """
    사용자 메시지를 chat_logic.ask()로 전달.
    내부적으로 Gemini + MCP 도구(get_guide)를 통해 가이드 데이터를 참고해 답변 생성.
    """
    answer = await ask(req.message)
    return {"answer": answer}


# =========================================================
# 사이트 접속 시 비밀번호 확인 (구버전 호환용)
# =========================================================

@app.post("/verify-password")
def verify_password(body: PasswordCheck):
    check_password(body.password)
    return {"ok": True}


# =========================================================
# 회원가입 / 로그인
# =========================================================

@app.post("/signup")
def signup(body: SignupRequest):
    """
    새 계정 가입 신청. 비밀번호는 해시로 저장하고, approved=False(승인 대기) 상태로 등록.
    관리자가 승인해야 실제 로그인이 가능해짐.
    """
    users = load_users()
    if body.username in users:
        raise HTTPException(status_code=400, detail="이미 존재하는 아이디입니다.")
    if len(body.password) < 4:
        raise HTTPException(status_code=400, detail="비밀번호는 4자 이상이어야 합니다.")
    hashed, salt = hash_password(body.password)
    users[body.username] = {"hashed": hashed, "salt": salt, "approved": False}
    save_users(users)
    return {"message": "가입 신청이 완료되었습니다. 관리자 승인 후 로그인 가능합니다."}


@app.post("/login")
def login(body: LoginRequest):
    """아이디+비밀번호 확인 후, 승인된 계정만 로그인 허용"""
    users = load_users()
    user = users.get(body.username)
    if not user or not verify_password_hash(body.password, user["salt"], user["hashed"]):
        raise HTTPException(status_code=403, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    if not user.get("approved"):
        raise HTTPException(status_code=403, detail="아직 관리자 승인 대기 중입니다.")
    return {"ok": True}


# =========================================================
# 관리자 전용: 회원 승인 / 관리
# 모든 엔드포인트가 admin_password(ADMIN_PASSWORD)로 별도 보호됨
# =========================================================

@app.get("/pending-users")
def pending_users(admin_password: str):
    """승인 대기 중인 사용자 아이디 목록 반환"""
    if admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="관리자 비밀번호가 틀렸습니다.")
    users = load_users()
    return [u for u, v in users.items() if not v.get("approved")]


@app.post("/approve-user")
def approve_user(body: ApproveRequest):
    """대기 중인 사용자를 승인 상태로 전환"""
    if body.admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="관리자 비밀번호가 틀렸습니다.")
    users = load_users()
    if body.username not in users:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")
    users[body.username]["approved"] = True
    save_users(users)
    return {"message": f"{body.username} 승인 완료"}


@app.get("/all-users")
def all_users(admin_password: str):
    """전체 회원 목록(아이디 + 승인 상태)을 반환 — "사용자 관리" 탭에서 사용"""
    if admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="관리자 비밀번호가 틀렸습니다.")
    users = load_users()
    return [{"username": u, "approved": v.get("approved", False)} for u, v in users.items()]


@app.post("/revoke-user")
def revoke_user(body: RevokeRequest):
    """회원 계정을 완전히 삭제 (강제 탈퇴). admin 계정 자신은 삭제 불가하도록 보호."""
    if body.admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="관리자 비밀번호가 틀렸습니다.")
    users = load_users()
    if body.username not in users:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")
    if body.username == "admin":
        raise HTTPException(status_code=400, detail="관리자 계정은 삭제할 수 없습니다.")
    del users[body.username]
    save_users(users)
    return {"message": f"{body.username} 계정이 삭제되었습니다."}