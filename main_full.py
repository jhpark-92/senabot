# main.py (전체 - 기존 내용에 이 버전으로 덮어쓰세요)
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import json

from chat_logic import ask

app = FastAPI()


class Correction(BaseModel):
    wrong_info: str
    correct_info: str


class ChatRequest(BaseModel):
    message: str


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
    with open("guide_content.txt", "r", encoding="utf-8") as f:
        guide_text = f.read()

    corrections = load_corrections()

    if corrections:
        corrections_text = "\n\n## 정정된 내용 (아래 내용을 우선 참고하세요)\n"
        for c in corrections:
            corrections_text += f"- 기존: {c['wrong_info']} → 정정: {c['correct_info']}\n"
        guide_text += corrections_text

    return {"guide": guide_text}


@app.get("/corrections")
def get_corrections_list():
    return load_corrections()


@app.post("/corrections")
def add_correction(correction: Correction):
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
