from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import json

from chat_logic import ask

app = FastAPI()


class Correction(BaseModel):
    wrong_info: str
    correct_info: str
    password: str

class ChatRequest(BaseModel):
    message: str


def load_guide_data():
    with open("guide_data.json", "r", encoding="utf-8") as f:
        return json.load(f)


def load_corrections():
    with open("corrections.json", "r", encoding="utf-8") as f:
        return json.load(f)


def save_corrections(corrections):
    with open("corrections.json", "w", encoding="utf-8") as f:
        json.dump(corrections, f, ensure_ascii=False, indent=2)


@app.get("/")
def read_index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/guide")
def get_guide():
    guide_data = load_guide_data()
    corrections = load_corrections()
    return {"guide_data": guide_data, "corrections": corrections}


@app.get("/corrections")
def get_corrections_list():
    return load_corrections()


@app.post("/corrections")
def add_correction(correction: Correction):
    check_password(correction.password)
    corrections = load_corrections()
    corrections.append({
        "wrong_info": correction.wrong_info,
        "correct_info": correction.correct_info
    })
    save_corrections(corrections)
    return {"message": "정정사항이 저장되었습니다.", "total_corrections": len(corrections)}


@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    answer = await ask(req.message)
    return {"answer": answer}

class DeckUpdate(BaseModel):
    counter_decks: list[str]
    priority_note: str = ""
    equipment: str = ""
    notes: str = ""
    password: str


def save_guide_data(data):
    with open("guide_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@app.put("/guide/{deck_name}")
def update_deck(deck_name: str, update: DeckUpdate):
    check_password(update.password)
    
    guide_data = load_guide_data()
    guide_data[deck_name] = {
        "counter_decks": update.counter_decks,
        "priority_note": update.priority_note,
        "equipment": update.equipment,
        "notes": update.notes,
    }
    save_guide_data(guide_data)
    return {"message": f"{deck_name} 정보가 수정되었습니다."}


import os

SHARED_PASSWORD = os.environ.get("SHARED_PASSWORD", "changeme")


def check_password(password: str):
    if password != SHARED_PASSWORD:
        raise HTTPException(status_code=403, detail="비밀번호가 올바르지 않습니다.")