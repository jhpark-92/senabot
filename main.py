"""
세나봇(길드전 가이드 챗봇) 백엔드 서버

주요 기능:
1. 정적 파일(index.html) 제공
2. 가이드 데이터 조회 / 수정 / 추가 / 삭제 (공격 가이드 / 방어 가이드)
3. 챗봇 대화 (Gemini + MCP 연동은 chat_logic.py에서 처리)
4. 회원가입 / 로그인 / 관리자 승인
5. 관리자용 회원 관리 (전체 조회, 삭제)
6. 공유 메모장
7. 레이드 공략 (강림 / 파괴신 / 돌발레이드)
8. 통합 수정 이력 ("정정 내역" 탭) — 덱 수정/추가/삭제, 메모, 레이드 저장을 전부 기록
9. 활동 로그 ("사용자 관리" 탭) — 로그인/챗봇 질문/저장 작업 전부 기록, 60일 지난 로그는 자동 정리
10. Railway Volume(영구 저장소) 대응
11. 공지사항 및 첨부파일 업로드 지원
"""

import os
import json
import shutil
import hashlib
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from chat_logic import ask

app = FastAPI()

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> str:
    """한국 시간(KST) 기준 현재 시각 문자열. Railway 서버는 기본 UTC라 명시적으로 변환해야 함."""
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M")


# =========================================================
# 영구 저장 경로 설정 (Railway Volume 대응)
#
# 로컬 개발 환경: DATA_DIR 환경변수가 없으므로 현재 폴더(".")를 그대로 사용
# 배포 환경(Railway): DATA_DIR=/data 로 설정해서, 재배포해도 안 사라지는
#                      Volume 경로에 사용자 데이터를 저장
#
# 주의: Volume 연결 이후에는 git push로 데이터 파일(guide_data.json 등)을
#       바꿔도 서비스에 자동 반영되지 않는다 (ensure_data_files가 최초 1회만
#       복사하기 때문). 데이터 갱신은 반드시 API(POST/PUT/DELETE 엔드포인트)를
#       통해 반영해야 한다.
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
    os.makedirs(path("uploads"), exist_ok=True)  # 업로드된 파일을 저장할 폴더 추가
    
    defaults = {
        "guide_data.json": {},
        "defense_data.json": {},  # 방어 가이드 데이터 추가
        "history.json": [],
        "users.json": {},
        "memo.json": {"content": ""},
        "activity_log.json": [],
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
        "notices.json": [],
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

    # ---- 1회성 마이그레이션: 예전 deck_history.json -> 새 history.json ----
    # history.json이 비어있는 상태에서, 예전 형식의 deck_history.json이
    # 남아있으면(Volume 안에 예전 데이터가 있으면) 새 통합 형식으로 변환해서 합친다.
    old_deck_history_path = path("deck_history.json")
    history_path = path("history.json")

    if os.path.exists(old_deck_history_path):
        with open(history_path, "r", encoding="utf-8") as f:
            current_history = json.load(f)

        if not current_history:  # 아직 새 이력이 하나도 안 쌓인 상태일 때만 마이그레이션
            with open(old_deck_history_path, "r", encoding="utf-8") as f:
                old_entries = json.load(f)

            migrated = []
            for entry in old_entries:
                migrated.append({
                    "type": "deck",
                    "target": entry.get("deck_name", "알 수 없음"),
                    "username": entry.get("username", ""),
                    "timestamp": entry.get("timestamp", ""),
                    "before": entry.get("before"),
                    "after": entry.get("after"),
                })

            with open(history_path, "w", encoding="utf-8") as f:
                json.dump(migrated, f, ensure_ascii=False, indent=2)

            print(f"[마이그레이션] deck_history.json {len(migrated)}건을 history.json으로 이전 완료")


ensure_data_files()


# =========================================================
# 비밀번호 / 로그인 관련 유틸리티
# =========================================================

# 회원 승인/관리 기능에 쓰이는 "관리자 비밀번호" (일반 로그인 비밀번호와는 별개)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme_admin")


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


def check_login(username: str, password: str):
    """
    아이디+비밀번호가 실제 승인된 회원 계정인지 확인.
    덱 수정/추가/삭제, 메모 저장, 레이드 저장 등
    "로그인한 회원이면 누구나 가능한" 작업에 공통으로 사용.
    """
    users = load_users()
    user = users.get(username)
    if not user or not verify_password_hash(password, user["salt"], user["hashed"]):
        raise HTTPException(status_code=403, detail="로그인 정보가 올바르지 않습니다.")
    if not user.get("approved"):
        raise HTTPException(status_code=403, detail="승인되지 않은 계정입니다.")

def check_admin_login(username: str, password: str):
    """로그인 정보가 유효하고, 그 계정이 admin인지 확인 (관리자 전용 기능 보호용)"""
    check_login(username, password)
    if username != "admin":
        raise HTTPException(status_code=403, detail="관리자 권한이 없습니다.")

# =========================================================
# 데이터 로드/저장 유틸 (가이드 데이터, 방어 데이터)
# =========================================================

def load_guide_data():
    with open(path("guide_data.json"), "r", encoding="utf-8") as f:
        return json.load(f)

def save_guide_data(data):
    with open(path("guide_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_defense_data():
    with open(path("defense_data.json"), "r", encoding="utf-8") as f:
        return json.load(f)

def save_defense_data(data):
    with open(path("defense_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================================================
# 통합 수정 이력 (history.json) — "정정 내역" 탭에 표시됨
#
# 덱 수정 / 덱 추가 / 덱 삭제 / 메모 저장 / 레이드 저장 등
# "실제 데이터가 바뀐" 저장 동작만 기록한다. (활동 전체 로그는 activity_log.json 참고)
# =========================================================

def load_history():
    try:
        with open(path("history.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_history(history):
    with open(path("history.json"), "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def add_history_entry(entry_type: str, target: str, username: str, before, after):
    """모든 저장 동작(덱 수정/추가/삭제, 메모, 레이드)에서 공통으로 호출하는 이력 기록 함수"""
    history = load_history()
    history.append({
        "type": entry_type,
        "target": target,
        "username": username,
        "timestamp": now_kst(),
        "before": before,
        "after": after,
    })
    save_history(history)

# =========================================================
# 활동 로그 (activity_log.json) — "사용자 관리" 탭에서 admin이 조회
#
# 로그인 / 챗봇 질문 / 저장 작업(덱·메모·레이드) 등 "누가 언제 무엇을 했는지"를
# history.json보다 더 넓은 범위로 기록한다 (로그인, 챗봇 질문까지 포함).
# 60일이 지난 로그는 새 로그가 추가될 때마다 자동으로 정리된다.
# =========================================================

LOG_RETENTION_DAYS = 60

def load_activity_log():
    try:
        with open(path("activity_log.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_activity_log(logs):
    with open(path("activity_log.json"), "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)

def cleanup_old_logs(logs, days: int = LOG_RETENTION_DAYS):
    """timestamp가 days일보다 오래된 로그를 제거. 형식이 깨진 로그는 안전하게 유지."""
    cutoff = datetime.now(KST) - timedelta(days=days)
    kept = []
    for log in logs:
        try:
            log_time = datetime.strptime(log["timestamp"], "%Y-%m-%d %H:%M").replace(tzinfo=KST)
            if log_time >= cutoff:
                kept.append(log)
        except (ValueError, KeyError):
            kept.append(log)
    return kept

def add_activity_log(log_type: str, username: str, detail: str = ""):
    """로그인/챗봇 질문/저장 작업 등 모든 활동을 기록. 기록할 때마다 60일 지난 로그를 함께 정리."""
    logs = load_activity_log()
    logs.append({
        "type": log_type,
        "username": username,
        "timestamp": now_kst(),
        "detail": detail,
    })
    logs = cleanup_old_logs(logs)
    save_activity_log(logs)

# =========================================================
# 회원 정보, 공유 메모장, 레이드 공략 로드/저장
# =========================================================

def load_users():
    with open(path("users.json"), "r", encoding="utf-8") as f:
        return json.load(f)

def save_users(users):
    with open(path("users.json"), "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

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
    username: str = ""  # 활동 로그에 "누가 물어봤는지" 기록하기 위해 사용 (없어도 동작은 함)

# ---- 공격 덱 ----
class DeckUpdate(BaseModel):
    """기존 덱 하나를 통째로 수정할 때 사용"""
    counter_decks: list[str]
    priority_note: str = ""
    equipment: str = ""
    notes: str = ""
    username: str
    password: str

class DeckCreate(BaseModel):
    """새 덱을 처음부터 등록할 때 사용 (덱 이름을 body에 포함)"""
    deck_name: str
    counter_decks: list[str] = []
    priority_note: str = ""
    equipment: str = ""
    notes: str = ""
    username: str
    password: str

class DeckDelete(BaseModel):
    """덱 삭제 시 인증 정보만 필요 (덱 이름은 URL 경로에 포함)"""
    username: str
    password: str

# ---- 방어 덱 (카운터 조합 없음) ----
class DefenseUpdate(BaseModel):
    priority_note: str = ""
    equipment: str = ""
    notes: str = ""
    username: str
    password: str

class DefenseCreate(BaseModel):
    deck_name: str
    priority_note: str = ""
    equipment: str = ""
    notes: str = ""
    username: str
    password: str

# ---- 기타 공통 ----
class SignupRequest(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class ApproveRequest(BaseModel):
    username: str
    password: str
    admin_username: str

class RevokeRequest(BaseModel):
    username: str
    password: str
    admin_username: str

class MemoUpdate(BaseModel):
    content: str
    username: str
    password: str

class RaidUpdate(BaseModel):
    boss: str | None = None   # "list" 타입 카테고리일 때만 사용 (예: "태오")
    content: str
    username: str
    password: str


# =========================================================
# 정적 파일 / 메인 페이지
# =========================================================

@app.get("/")
def read_index():
    """루트 접속 시 프론트엔드(index.html) 반환"""
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory=path("uploads")), name="uploads")


# =========================================================
# 공격 가이드 조회 / 수정 / 추가 / 삭제
# =========================================================

@app.get("/guide")
def get_guide():
    """전체 공격 가이드 데이터를 반환. 인증 불필요 (조회는 누구나 가능)."""
    return {"guide_data": load_guide_data()}

@app.put("/guide/{deck_name}")
def update_deck(deck_name: str, update: DeckUpdate):
    """기존 공격 덱 하나의 정보를 통째로 덮어씀."""
    check_login(update.username, update.password)
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

    add_history_entry("deck", deck_name, update.username, before, after)
    add_activity_log("save", update.username, f"공격 덱 수정: {deck_name}")
    return {"message": f"{deck_name} 정보가 수정되었습니다."}

@app.post("/guide")
def create_deck(body: DeckCreate):
    """완전히 새로운 공격 덱을 목록에 처음 등록."""
    check_login(body.username, body.password)
    guide_data = load_guide_data()
    if body.deck_name in guide_data:
        raise HTTPException(status_code=400, detail="이미 존재하는 덱 이름입니다.")

    after = {
        "counter_decks": body.counter_decks,
        "priority_note": body.priority_note,
        "equipment": body.equipment,
        "notes": body.notes,
    }
    guide_data[body.deck_name] = after
    save_guide_data(guide_data)

    add_history_entry("deck_create", body.deck_name, body.username, None, after)
    add_activity_log("save", body.username, f"공격 덱 추가: {body.deck_name}")
    return {"message": f"{body.deck_name} 덱이 추가되었습니다."}

@app.delete("/guide/{deck_name}")
def delete_deck(deck_name: str, body: DeckDelete):
    """공격 덱을 완전히 삭제."""
    check_login(body.username, body.password)
    guide_data = load_guide_data()
    if deck_name not in guide_data:
        raise HTTPException(status_code=404, detail="존재하지 않는 덱입니다.")

    before = guide_data[deck_name]
    del guide_data[deck_name]
    save_guide_data(guide_data)

    add_history_entry("deck_delete", deck_name, body.username, before, None)
    add_activity_log("save", body.username, f"공격 덱 삭제: {deck_name}")
    return {"message": f"{deck_name} 덱이 삭제되었습니다."}


# =========================================================
# 방어 가이드 조회 / 수정 / 추가 / 삭제
# =========================================================

@app.get("/defense")
def get_defense():
    """방어 가이드 데이터를 반환."""
    return {"defense_data": load_defense_data()}

@app.put("/defense/{deck_name}")
def update_defense(deck_name: str, update: DefenseUpdate):
    """방어 덱 하나를 통째로 덮어씀."""
    check_login(update.username, update.password)
    defense_data = load_defense_data()
    before = defense_data.get(deck_name, {})

    after = {
        "priority_note": update.priority_note,
        "equipment": update.equipment,
        "notes": update.notes,
    }
    defense_data[deck_name] = after
    save_defense_data(defense_data)

    add_history_entry("defense", deck_name, update.username, before, after)
    add_activity_log("save", update.username, f"방어 덱 수정: {deck_name}")
    return {"message": f"{deck_name} 방어 배치가 수정되었습니다."}

@app.post("/defense")
def create_defense(body: DefenseCreate):
    """새로운 방어 덱 등록."""
    check_login(body.username, body.password)
    defense_data = load_defense_data()
    if body.deck_name in defense_data:
        raise HTTPException(status_code=400, detail="이미 존재하는 방어 덱 이름입니다.")

    after = {
        "priority_note": body.priority_note,
        "equipment": body.equipment,
        "notes": body.notes,
    }
    defense_data[body.deck_name] = after
    save_defense_data(defense_data)

    add_history_entry("defense_create", body.deck_name, body.username, None, after)
    add_activity_log("save", body.username, f"방어 덱 추가: {body.deck_name}")
    return {"message": f"{body.deck_name} 방어 배치가 추가되었습니다."}

@app.delete("/defense/{deck_name}")
def delete_defense(deck_name: str, body: DeckDelete):
    """방어 덱 완전 삭제."""
    check_login(body.username, body.password)
    defense_data = load_defense_data()
    if deck_name not in defense_data:
        raise HTTPException(status_code=404, detail="존재하지 않는 덱입니다.")

    before = defense_data[deck_name]
    del defense_data[deck_name]
    save_defense_data(defense_data)

    add_history_entry("defense_delete", deck_name, body.username, before, None)
    add_activity_log("save", body.username, f"방어 덱 삭제: {deck_name}")
    return {"message": f"{deck_name} 방어 배치가 삭제되었습니다."}


# =========================================================
# 통합 수정 이력, 공유 메모장, 레이드
# =========================================================

@app.get("/corrections")
def get_corrections_list():
    """모든 저장 동작의 이력을 최신순으로 반환"""
    return list(reversed(load_history()))

@app.get("/memo")
def get_memo():
    return load_memo()

@app.put("/memo")
def update_memo(body: MemoUpdate):
    """메모장 내용 저장. 저장할 때마다 이력/활동 로그에도 기록."""
    check_login(body.username, body.password)
    before = load_memo()
    after = {"content": body.content}
    save_memo(after)
    add_history_entry("memo", "메모장", body.username, before.get("content", ""), body.content)
    add_activity_log("save", body.username, "메모 저장")
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
    """특정 카테고리(강림/파괴신/돌발레이드)의 공략 내용을 수정."""
    check_login(update.username, update.password)
    raid_data = load_raid_data()

    if category not in raid_data:
        raise HTTPException(status_code=404, detail="존재하지 않는 카테고리입니다.")

    entry = raid_data[category]

    if entry["type"] == "single":
        before = entry.get("content", "")
        entry["content"] = update.content
        target_label = category
        after = update.content
    else:  # "list" 타입 (보스별 관리)
        if not update.boss or update.boss not in entry["bosses"]:
            raise HTTPException(status_code=400, detail="존재하지 않는 보스입니다.")
        before = entry["bosses"].get(update.boss, "")
        entry["bosses"][update.boss] = update.content
        target_label = f"{category} - {update.boss}"
        after = update.content

    save_raid_data(raid_data)

    add_history_entry("raid", target_label, update.username, before, after)
    add_activity_log("save", update.username, f"레이드 저장: {target_label}")
    return {"message": "저장되었습니다."}


# =========================================================
# 챗봇 대화
# =========================================================

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    """
    사용자 메시지를 chat_logic.ask()로 전달.
    내부적으로 Gemini + MCP 도구(get_guide)를 통해 가이드 데이터를 참고해 답변 생성.
    질문 내용도 활동 로그에 남긴다.
    """
    answer = await ask(req.message)
    add_activity_log("chat", req.username, req.message)
    return {"answer": answer}


# =========================================================
# 회원가입 / 로그인
# =========================================================

@app.post("/signup")
def signup(body: SignupRequest):
    """새 계정 가입 신청. 비밀번호는 해시로 저장하고, approved=False(승인 대기) 상태로 등록."""
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
    """아이디+비밀번호 확인 후, 승인된 계정만 로그인 허용. 로그인 성공 시 활동 로그에 기록."""
    users = load_users()
    user = users.get(body.username)
    if not user or not verify_password_hash(body.password, user["salt"], user["hashed"]):
        raise HTTPException(status_code=403, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    if not user.get("approved"):
        raise HTTPException(status_code=403, detail="아직 관리자 승인 대기 중입니다.")
    add_activity_log("login", body.username)
    return {"ok": True}


# =========================================================
# 관리자 전용: 회원 승인 / 관리 / 활동 로그 조회
# 모든 엔드포인트가 admin_password(ADMIN_PASSWORD)로 별도 보호됨
# =========================================================

@app.get("/pending-users")
def pending_users(username: str, password: str):
    """승인 대기 중인 사용자 아이디 목록 반환"""
    check_admin_login(username, password)
    users = load_users()
    return [u for u, v in users.items() if not v.get("approved")]

@app.post("/approve-user")
def approve_user(body: ApproveRequest):
    """대기 중인 사용자를 승인 상태로 전환"""
    check_admin_login(body.admin_username, body.password)
    users = load_users()
    if body.username not in users:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")
    users[body.username]["approved"] = True
    save_users(users)
    return {"message": f"{body.username} 승인 완료"}

@app.get("/all-users")
def all_users(username: str, password: str):
    """전체 회원 목록(아이디 + 승인 상태)을 반환"""
    check_admin_login(username, password)
    users = load_users()
    return [{"username": u, "approved": v.get("approved", False)} for u, v in users.items()]

@app.post("/revoke-user")
def revoke_user(body: RevokeRequest):
    """회원 계정을 완전히 삭제"""
    check_admin_login(body.admin_username, body.password)
    users = load_users()
    if body.username not in users:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")
    if body.username == "admin":
        raise HTTPException(status_code=400, detail="관리자 계정은 삭제할 수 없습니다.")
    del users[body.username]
    save_users(users)
    return {"message": f"{body.username} 계정이 삭제되었습니다."}

@app.get("/activity-log")
def get_activity_log(username: str, password: str, username_filter: str = ""):
    """전체 활동 로그를 최신순으로 반환"""
    check_admin_login(username, password)
    logs = load_activity_log()
    if username_filter:
        logs = [l for l in logs if l["username"] == username_filter]
    return list(reversed(logs))


# =========================================================
# 공지사항 관리 (파일 업로드 지원)
# =========================================================

def load_notices():
    try:
        with open(path("notices.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_notices(notices):
    with open(path("notices.json"), "w", encoding="utf-8") as f:
        json.dump(notices, f, ensure_ascii=False, indent=2)

class NoticeDelete(BaseModel):
    username: str
    password: str

@app.get("/notices")
def get_notices():
    """공지사항 목록을 최신순으로 반환. 인증 불필요 (누구나 조회 가능)."""
    notices = load_notices()
    return list(reversed(notices))

@app.post("/notices")
async def create_notice(
    title: str = Form(...),
    content: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    file: UploadFile | None = File(None)
):
    """새 공지사항 등록 및 첨부파일 처리. admin만 가능."""
    check_admin_login(username, password)

    file_url = None
    if file and file.filename:
        ext = file.filename.split('.')[-1]
        filename = f"notice_{secrets.token_hex(4)}.{ext}"
        file_path = path(os.path.join("uploads", filename))
        with open(file_path, "wb") as f:
            f.write(await file.read())
        file_url = f"/uploads/{filename}"

    notices = load_notices()
    new_id = (max([n["id"] for n in notices], default=0)) + 1
    notices.append({
        "id": new_id,
        "title": title,
        "content": content,
        "file_url": file_url,
        "username": username,
        "timestamp": now_kst(),
    })
    save_notices(notices)

    add_activity_log("save", username, f"공지 등록: {title}")
    return {"message": "공지사항이 등록되었습니다."}

@app.delete("/notices/{notice_id}")
def delete_notice(notice_id: int, body: NoticeDelete):
    """공지사항 삭제. admin만 가능."""
    check_admin_login(body.username, body.password)
    notices = load_notices()
    notices = [n for n in notices if n["id"] != notice_id]
    save_notices(notices)
    return {"message": "공지사항이 삭제되었습니다."}