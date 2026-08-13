import os
import json
import hashlib
import secrets
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from chat_logic import ask

app = FastAPI()


# ---------------- 비밀번호 관련 ----------------

SHARED_PASSWORD = os.environ.get("SHARED_PASSWORD", "changeme")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme_admin")


def check_password(password: str):
    if password != SHARED_PASSWORD:
        raise HTTPException(status_code=403, detail="비밀번호가 올바르지 않습니다.")


def hash_password(password: str, salt: str = None):
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
    return hashed, salt


def verify_password_hash(password: str, salt: str, hashed: str) -> bool:
    check, _ = hash_password(password, salt)
    return check == hashed


# ---------------- 가이드 데이터 ----------------

def load_guide_data():
    with open("guide_data.json", "r", encoding="utf-8") as f:
        return json.load(f)


def save_guide_data(data):
    with open("guide_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------- 덱 수정 이력 (구 "정정 내역") ----------------

def load_deck_history():
    try:
        with open("deck_history.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def save_deck_history(history):
    with open("deck_history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ---------------- 회원가입 / 로그인 ----------------

def load_users():
    with open("users.json", "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(users):
    with open("users.json", "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


# ---------------- Pydantic 모델 ----------------

class ChatRequest(BaseModel):
    message: str


class DeckUpdate(BaseModel):
    counter_decks: list[str]
    priority_note: str = ""
    equipment: str = ""
    notes: str = ""
    password: str


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


# ---------------- 정적 파일 / 인덱스 ----------------

@app.get("/")
def read_index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------- 가이드 조회 / 수정 ----------------

@app.get("/guide")
def get_guide():
    guide_data = load_guide_data()
    return {"guide_data": guide_data}


@app.put("/guide/{deck_name}")
def update_deck(deck_name: str, update: DeckUpdate):
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

    history = load_deck_history()
    history.append({
        "deck_name": deck_name,
        "before": before,
        "after": after,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    save_deck_history(history)

    return {"message": f"{deck_name} 정보가 수정되었습니다."}


# ---------------- 수정 이력 (구 "정정 내역") ----------------

@app.get("/corrections")
def get_corrections_list():
    history = load_deck_history()
    return list(reversed(history))  # 최신 수정이 위로 오도록


# ---------------- 챗봇 ----------------

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    answer = await ask(req.message)
    return {"answer": answer}


# ---------------- 접속 비밀번호 확인 ----------------

@app.post("/verify-password")
def verify_password(body: PasswordCheck):
    check_password(body.password)  # 틀리면 403 에러 자동 발생
    return {"ok": True}


# ---------------- 회원가입 / 로그인 / 승인 ----------------

@app.post("/signup")
def signup(body: SignupRequest):
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
    users = load_users()
    user = users.get(body.username)
    if not user or not verify_password_hash(body.password, user["salt"], user["hashed"]):
        raise HTTPException(status_code=403, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    if not user.get("approved"):
        raise HTTPException(status_code=403, detail="아직 관리자 승인 대기 중입니다.")
    return {"ok": True}


@app.get("/pending-users")
def pending_users(admin_password: str):
    if admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="관리자 비밀번호가 틀렸습니다.")
    users = load_users()
    return [u for u, v in users.items() if not v.get("approved")]


@app.post("/approve-user")
def approve_user(body: ApproveRequest):
    if body.admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="관리자 비밀번호가 틀렸습니다.")
    users = load_users()
    if body.username not in users:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")
    users[body.username]["approved"] = True
    save_users(users)
    return {"message": f"{body.username} 승인 완료"}