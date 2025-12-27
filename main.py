"""Main FastAPI application for the cognitive-reinforcement-backend."""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import (
    Body,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    UploadFile,
)
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

import db
import quiz
import storage

load_dotenv()

API_KEY = os.getenv("APP_API_KEY")

app = FastAPI(title="cognitive-reinforcement-backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def verify_api_key(x_api_key: Annotated[Optional[str], Header()] = None):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server missing APP_API_KEY")
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


AuthDependency = Depends(verify_api_key)


@app.on_event("startup")
def _startup():
    engine = db.get_engine()
    db.create_tables(engine)


class PatientCreate(BaseModel):
    full_name: str
    dob: str
    phone: Optional[str] = None
    address: Optional[str] = None


class PatientResponse(PatientCreate):
    id: str
    created_at: datetime


class FamilyMemberCreate(BaseModel):
    full_name: str
    relationship: str
    photo_blob_path: Optional[str] = None


class FamilyMemberResponse(FamilyMemberCreate):
    id: str
    patient_id: str
    created_at: datetime


class KnowledgeItemCreate(BaseModel):
    category: str
    label: str
    value: str
    sensitivity_level: int = Field(0, ge=0, le=5)
    is_active: bool = True


class KnowledgeItemResponse(KnowledgeItemCreate):
    id: str
    patient_id: str
    created_at: datetime


class QuizQuestionPayload(BaseModel):
    question_type: str
    prompt: str
    options: Optional[List[str]] = None
    item_type: str
    item_id: str
    difficulty: int
    acceptable_answers: Optional[List[str]] = None


class QuizQuestionResponse(QuizQuestionPayload):
    question_id: str


class QuizGenerateResponse(BaseModel):
    session_id: str
    questions: List[QuizQuestionResponse]


class QuizSubmitItem(BaseModel):
    question_id: str
    user_answer: str | int | bool | dict | list
    response_time_ms: int


class QuizSubmitResponse(BaseModel):
    session_id: str
    score: float
    total_questions: int
    correct: int
    avg_response_time_ms: Optional[float]
    weak_items: List[str]


class AnalyticsSummary(BaseModel):
    accuracy_by_category: dict
    last_seen: dict
    next_due: dict


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/patients", dependencies=[AuthDependency], response_model=PatientResponse)
def create_patient(payload: PatientCreate):
    return db.create_patient(db.get_engine(), payload.dict())


@app.get("/patients", dependencies=[AuthDependency], response_model=List[PatientResponse])
def list_patients():
    return db.list_patients(db.get_engine())


@app.get(
    "/patients/{patient_id}",
    dependencies=[AuthDependency],
    response_model=PatientResponse,
)
def get_patient(patient_id: str):
    patient = db.get_patient(db.get_engine(), patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@app.post(
    "/patients/{patient_id}/family",
    dependencies=[AuthDependency],
    response_model=FamilyMemberResponse,
)
def add_family_member(patient_id: str, payload: FamilyMemberCreate):
    return db.add_family_member(db.get_engine(), patient_id, payload.dict())


@app.get(
    "/patients/{patient_id}/family",
    dependencies=[AuthDependency],
    response_model=List[FamilyMemberResponse],
)
def list_family_members(patient_id: str):
    return db.list_family_members(db.get_engine(), patient_id)


@app.post(
    "/patients/{patient_id}/family/{family_id}/photo",
    dependencies=[AuthDependency],
)
async def upload_family_photo(
    patient_id: str, family_id: str, file: UploadFile = File(...)
):
    blob_path = await storage.upload_family_photo(patient_id, family_id, file)
    db.update_family_photo(db.get_engine(), family_id, blob_path)
    return {"blob_path": blob_path}


@app.post(
    "/patients/{patient_id}/knowledge",
    dependencies=[AuthDependency],
    response_model=KnowledgeItemResponse,
)
def add_knowledge_item(patient_id: str, payload: KnowledgeItemCreate):
    return db.add_knowledge_item(db.get_engine(), patient_id, payload.dict())


@app.get(
    "/patients/{patient_id}/knowledge",
    dependencies=[AuthDependency],
    response_model=List[KnowledgeItemResponse],
)
def list_knowledge_items(patient_id: str, category: Optional[str] = None):
    return db.list_knowledge_items(db.get_engine(), patient_id, category)


@app.post(
    "/patients/{patient_id}/uploads",
    dependencies=[AuthDependency],
)
async def upload_patient_doc(patient_id: str, file: UploadFile = File(...)):
    blob_path = await storage.upload_patient_document(patient_id, file)
    return {"blob_path": blob_path}


@app.post(
    "/patients/{patient_id}/quiz/generate",
    dependencies=[AuthDependency],
    response_model=QuizGenerateResponse,
)
def generate_quiz(
    patient_id: str,
    n: int = 7,
    include_sensitive: bool = False,
    reveal_answers: bool = False,
):
    engine = db.get_engine()
    patient = db.get_patient(engine, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    family_members = db.list_family_members(engine, patient_id)
    knowledge_items = db.list_knowledge_items(engine, patient_id, None)
    due_items = db.due_items(engine, patient_id)
    questions = quiz.generate_quiz_questions(
        patient=patient,
        family_members=family_members,
        knowledge_items=knowledge_items,
        due_items=due_items,
        n=n,
        include_sensitive=include_sensitive,
    )
    session_id = db.create_session(
        engine, patient_id, total_questions=len(questions), status="active"
    )
    response_questions = []
    for q in questions:
        question_id = db.add_question(
            engine,
            session_id,
            question_type=q["question_type"],
            payload_json=json.dumps(q),
            correct_answer_json=json.dumps(q.get("correct_answer")),
        )
        response_questions.append(
            QuizQuestionResponse(
                question_id=question_id,
                question_type=q["question_type"],
                prompt=q["prompt"],
                options=q.get("options"),
                item_type=q["item_type"],
                item_id=q["item_id"],
                difficulty=q["difficulty"],
                acceptable_answers=q.get("acceptable_answers"),
            )
        )
    if not reveal_answers:
        for idx, item in enumerate(response_questions):
            response_questions[idx].acceptable_answers = None
    return QuizGenerateResponse(session_id=session_id, questions=response_questions)


@app.post(
    "/quiz/{session_id}/submit",
    dependencies=[AuthDependency],
    response_model=QuizSubmitResponse,
)
def submit_quiz(
    session_id: str, submissions: Annotated[List[QuizSubmitItem], Body(...)]
):
    engine = db.get_engine()
    session = db.get_session(engine, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    questions = db.list_questions(engine, session_id)
    qmap = {q["id"]: q for q in questions}
    results = []
    correct_count = 0
    total_time = 0
    for item in submissions:
        question = qmap.get(item.question_id)
        if not question:
            raise HTTPException(status_code=400, detail="Invalid question id")
        payload = json.loads(question["payload_json"])
        correct_answer = payload.get("correct_answer")
        acceptable_answers = payload.get("acceptable_answers") or []
        is_correct = quiz.evaluate_answer(
            payload["question_type"], correct_answer, item.user_answer, acceptable_answers
        )
        if is_correct:
            correct_count += 1
        total_time += item.response_time_ms
        db.add_response(
            engine,
            session_id=session_id,
            question_id=item.question_id,
            user_answer_json=json.dumps(item.user_answer),
            correct=is_correct,
            response_time_ms=item.response_time_ms,
        )
        mastery_update = quiz.compute_mastery_update(
            engine,
            patient_id=session["patient_id"],
            payload=payload,
            correct=is_correct,
            response_time_ms=item.response_time_ms,
        )
        if mastery_update:
            db.update_mastery(engine, mastery_update)
        results.append({"question_id": item.question_id, "correct": is_correct})
    score = correct_count / max(len(submissions), 1)
    avg_time = total_time / max(len(submissions), 1)
    db.complete_session(engine, session_id, score=score, avg_response_time_ms=avg_time)
    weak_items = [
        r["question_id"] for r in results if not r["correct"]
    ]
    return QuizSubmitResponse(
        session_id=session_id,
        score=score,
        total_questions=len(submissions),
        correct=correct_count,
        avg_response_time_ms=avg_time,
        weak_items=weak_items,
    )


@app.get(
    "/patients/{patient_id}/analytics/summary",
    dependencies=[AuthDependency],
    response_model=AnalyticsSummary,
)
def analytics_summary(patient_id: str, days: int = 30):
    data = db.analytics_summary(db.get_engine(), patient_id, days=days)
    return JSONResponse(content=data)
