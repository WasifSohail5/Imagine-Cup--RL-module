"""Database helpers for Azure SQL (or compatible) connections."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    select,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

metadata = MetaData()


def _uuid() -> str:
    return str(uuid.uuid4())


patients = Table(
    "patients",
    metadata,
    Column("id", String(36), primary_key=True, default=_uuid),
    Column("full_name", String(255), nullable=False),
    Column("dob", String(50), nullable=False),
    Column("phone", String(50)),
    Column("address", String(255)),
    Column("created_at", DateTime, default=datetime.utcnow),
)

family_members = Table(
    "family_members",
    metadata,
    Column("id", String(36), primary_key=True, default=_uuid),
    Column("patient_id", String(36), nullable=False),
    Column("full_name", String(255), nullable=False),
    Column("relationship", String(100), nullable=False),
    Column("photo_blob_path", String(500)),
    Column("created_at", DateTime, default=datetime.utcnow),
)

knowledge_items = Table(
    "knowledge_items",
    metadata,
    Column("id", String(36), primary_key=True, default=_uuid),
    Column("patient_id", String(36), nullable=False),
    Column("category", String(100), nullable=False),
    Column("label", String(255), nullable=False),
    Column("value", String(500), nullable=False),
    Column("sensitivity_level", Integer, default=0),
    Column("is_active", Boolean, default=True),
    Column("created_at", DateTime, default=datetime.utcnow),
)

quiz_sessions = Table(
    "quiz_sessions",
    metadata,
    Column("id", String(36), primary_key=True, default=_uuid),
    Column("patient_id", String(36), nullable=False),
    Column("created_at", DateTime, default=datetime.utcnow),
    Column("status", String(50)),
    Column("total_questions", Integer),
    Column("score", Float),
    Column("avg_response_time_ms", Float),
)

quiz_questions = Table(
    "quiz_questions",
    metadata,
    Column("id", String(36), primary_key=True, default=_uuid),
    Column("session_id", String(36), nullable=False),
    Column("question_type", String(50), nullable=False),
    Column("payload_json", String(4000), nullable=False),
    Column("correct_answer_json", String(2000)),
    Column("created_at", DateTime, default=datetime.utcnow),
)

quiz_responses = Table(
    "quiz_responses",
    metadata,
    Column("id", String(36), primary_key=True, default=_uuid),
    Column("session_id", String(36), nullable=False),
    Column("question_id", String(36), nullable=False),
    Column("user_answer_json", String(2000)),
    Column("correct", Boolean, default=False),
    Column("response_time_ms", Integer),
    Column("created_at", DateTime, default=datetime.utcnow),
)

mastery = Table(
    "mastery",
    metadata,
    Column("id", String(36), primary_key=True, default=_uuid),
    Column("patient_id", String(36), nullable=False),
    Column("item_type", String(20), nullable=False),
    Column("item_id", String(36), nullable=False),
    Column("mastery_score", Float, default=0.0),
    Column("consecutive_correct", Integer, default=0),
    Column("consecutive_incorrect", Integer, default=0),
    Column("last_seen_at", DateTime),
    Column("next_due_at", DateTime),
)

engine_cache: Optional[Engine] = None


def get_engine() -> Engine:
    """Create or return a cached SQLAlchemy engine."""
    global engine_cache
    if engine_cache:
        return engine_cache
    conn_str = os.getenv("SQL_CONNECTION_STRING")
    if not conn_str:
        raise RuntimeError("SQL_CONNECTION_STRING is not configured")
    if conn_str.startswith("sqlite"):
        engine_cache = create_engine(
            conn_str,
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine_cache = create_engine(conn_str, future=True)
    return engine_cache


def create_tables(engine: Engine) -> None:
    metadata.create_all(engine)


def _row_to_dict(row) -> dict:
    if not row:
        return None
    mapping = row._mapping
    return {k: mapping[k] for k in mapping.keys()}


def create_patient(engine: Engine, data: Dict[str, Any]) -> Dict[str, Any]:
    patient_id = _uuid()
    with engine.begin() as conn:
        conn.execute(
            patients.insert().values(
                id=patient_id,
                full_name=data["full_name"],
                dob=data["dob"],
                phone=data.get("phone"),
                address=data.get("address"),
                created_at=datetime.utcnow(),
            )
        )
    return get_patient(engine, patient_id)


def get_patient(engine: Engine, patient_id: str) -> Optional[Dict[str, Any]]:
    with engine.connect() as conn:
        row = conn.execute(select(patients).where(patients.c.id == patient_id)).first()
        return _row_to_dict(row)


def list_patients(engine: Engine) -> List[Dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(select(patients)).all()
        return [_row_to_dict(r) for r in rows]


def add_family_member(engine: Engine, patient_id: str, data: Dict[str, Any]):
    fam_id = _uuid()
    with engine.begin() as conn:
        conn.execute(
            family_members.insert().values(
                id=fam_id,
                patient_id=patient_id,
                full_name=data["full_name"],
                relationship=data["relationship"],
                photo_blob_path=data.get("photo_blob_path"),
                created_at=datetime.utcnow(),
            )
        )
    return get_family_member(engine, fam_id)


def get_family_member(engine: Engine, family_id: str):
    with engine.connect() as conn:
        row = conn.execute(
            select(family_members).where(family_members.c.id == family_id)
        ).first()
        return _row_to_dict(row)


def update_family_photo(engine: Engine, family_id: str, blob_path: str):
    with engine.begin() as conn:
        conn.execute(
            update(family_members)
            .where(family_members.c.id == family_id)
            .values(photo_blob_path=blob_path)
        )


def list_family_members(engine: Engine, patient_id: str):
    with engine.connect() as conn:
        rows = conn.execute(
            select(family_members).where(family_members.c.patient_id == patient_id)
        ).all()
        return [_row_to_dict(r) for r in rows]


def add_knowledge_item(engine: Engine, patient_id: str, data: Dict[str, Any]):
    item_id = _uuid()
    with engine.begin() as conn:
        conn.execute(
            knowledge_items.insert().values(
                id=item_id,
                patient_id=patient_id,
                category=data["category"],
                label=data["label"],
                value=data["value"],
                sensitivity_level=int(data.get("sensitivity_level", 0)),
                is_active=data.get("is_active", True),
                created_at=datetime.utcnow(),
            )
        )
    return get_knowledge_item(engine, item_id)


def get_knowledge_item(engine: Engine, item_id: str):
    with engine.connect() as conn:
        row = conn.execute(
            select(knowledge_items).where(knowledge_items.c.id == item_id)
        ).first()
        return _row_to_dict(row)


def list_knowledge_items(engine: Engine, patient_id: str, category: Optional[str]):
    stmt = select(knowledge_items).where(knowledge_items.c.patient_id == patient_id)
    if category:
        stmt = stmt.where(knowledge_items.c.category == category)
    with engine.connect() as conn:
        rows = conn.execute(stmt).all()
        return [_row_to_dict(r) for r in rows]


def create_session(engine: Engine, patient_id: str, total_questions: int, status: str):
    session_id = _uuid()
    with engine.begin() as conn:
        conn.execute(
            quiz_sessions.insert().values(
                id=session_id,
                patient_id=patient_id,
                created_at=datetime.utcnow(),
                status=status,
                total_questions=total_questions,
            )
        )
    return session_id


def get_session(engine: Engine, session_id: str):
    with engine.connect() as conn:
        row = conn.execute(
            select(quiz_sessions).where(quiz_sessions.c.id == session_id)
        ).first()
        return _row_to_dict(row)


def add_question(
    engine: Engine, session_id: str, question_type: str, payload_json: str, correct_answer_json: str
) -> str:
    question_id = _uuid()
    with engine.begin() as conn:
        conn.execute(
            quiz_questions.insert().values(
                id=question_id,
                session_id=session_id,
                question_type=question_type,
                payload_json=payload_json,
                correct_answer_json=correct_answer_json,
                created_at=datetime.utcnow(),
            )
        )
    return question_id


def list_questions(engine: Engine, session_id: str):
    with engine.connect() as conn:
        rows = conn.execute(
            select(quiz_questions).where(quiz_questions.c.session_id == session_id)
        ).all()
        return [_row_to_dict(r) for r in rows]


def add_response(
    engine: Engine,
    session_id: str,
    question_id: str,
    user_answer_json: str,
    correct: bool,
    response_time_ms: int,
):
    with engine.begin() as conn:
        conn.execute(
            quiz_responses.insert().values(
                id=_uuid(),
                session_id=session_id,
                question_id=question_id,
                user_answer_json=user_answer_json,
                correct=correct,
                response_time_ms=response_time_ms,
                created_at=datetime.utcnow(),
            )
        )


def complete_session(engine: Engine, session_id: str, score: float, avg_response_time_ms: float):
    with engine.begin() as conn:
        conn.execute(
            update(quiz_sessions)
            .where(quiz_sessions.c.id == session_id)
            .values(
                status="completed",
                score=score,
                avg_response_time_ms=avg_response_time_ms,
            )
        )


def _get_mastery_row(engine: Engine, patient_id: str, item_type: str, item_id: str):
    with engine.connect() as conn:
        row = conn.execute(
            select(mastery).where(
                mastery.c.patient_id == patient_id,
                mastery.c.item_type == item_type,
                mastery.c.item_id == item_id,
            )
        ).first()
        return _row_to_dict(row)


def update_mastery(engine: Engine, payload: Dict[str, Any]):
    existing = _get_mastery_row(
        engine, payload["patient_id"], payload["item_type"], payload["item_id"]
    )
    now = datetime.utcnow()
    values = {
        "patient_id": payload["patient_id"],
        "item_type": payload["item_type"],
        "item_id": payload["item_id"],
        "mastery_score": float(payload.get("mastery_score", 0)),
        "consecutive_correct": int(payload.get("consecutive_correct", 0)),
        "consecutive_incorrect": int(payload.get("consecutive_incorrect", 0)),
        "last_seen_at": payload.get("last_seen_at", now),
        "next_due_at": payload.get("next_due_at"),
    }
    with engine.begin() as conn:
        if existing:
            conn.execute(
                update(mastery)
                .where(mastery.c.id == existing["id"])
                .values(**values)
            )
        else:
            values["id"] = _uuid()
            conn.execute(mastery.insert().values(**values))


def due_items(engine: Engine, patient_id: str):
    """Return items due for review, including ones missing mastery rows."""
    now = datetime.utcnow()
    with engine.connect() as conn:
        # existing mastery rows due now
        mastery_rows = conn.execute(
            select(mastery).where(
                mastery.c.patient_id == patient_id,
                (mastery.c.next_due_at == None) | (mastery.c.next_due_at <= now),  # noqa: E711
            )
        ).all()
        due_list = [_row_to_dict(r) for r in mastery_rows]

        # find knowledge/family items without mastery rows
        known_ids = {row["item_id"] for row in due_list}
        family_rows = conn.execute(
            select(family_members.c.id).where(family_members.c.patient_id == patient_id)
        ).all()
        knowledge_rows = conn.execute(
            select(knowledge_items.c.id, knowledge_items.c.sensitivity_level).where(
                knowledge_items.c.patient_id == patient_id
            )
        ).all()

        for row in family_rows:
            if row.id not in known_ids:  # type: ignore
                due_list.append(
                    {
                        "item_type": "family",
                        "item_id": row.id,  # type: ignore
                        "next_due_at": None,
                        "last_seen_at": None,
                    }
                )
                known_ids.add(row.id)  # type: ignore

        for row in knowledge_rows:
            if row.id not in known_ids:  # type: ignore
                due_list.append(
                    {
                        "item_type": "knowledge",
                        "item_id": row.id,  # type: ignore
                        "sensitivity_level": row.sensitivity_level,  # type: ignore
                        "next_due_at": None,
                        "last_seen_at": None,
                    }
                )
                known_ids.add(row.id)  # type: ignore
    return due_list


def analytics_summary(engine: Engine, patient_id: str, days: int = 30) -> Dict[str, Any]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    data = {"accuracy_by_category": {}, "last_seen": {}, "next_due": {}}
    with engine.connect() as conn:
        # accuracy by category from quiz_responses joined with questions
        rows = conn.execute(
            select(
                quiz_questions.c.id,
                quiz_questions.c.payload_json,
                quiz_responses.c.correct,
            ).join(
                quiz_responses, quiz_questions.c.id == quiz_responses.c.question_id
            ).where(
                quiz_responses.c.created_at >= cutoff
            )
        ).all()
        stats = {}
        for r in rows:
            payload = json.loads(r.payload_json)
            category = payload.get("item_type", "unknown")
            stat = stats.setdefault(category, {"correct": 0, "total": 0})
            stat["total"] += 1
            if r.correct:
                stat["correct"] += 1
        for category, stat in stats.items():
            data["accuracy_by_category"][category] = stat["correct"] / max(
                stat["total"], 1
            )
        # last seen / next due from mastery
        mrows = conn.execute(
            select(mastery).where(mastery.c.patient_id == patient_id)
        ).all()
        for r in mrows:
            key = f"{r.item_type}:{r.item_id}"
            data["last_seen"][key] = (
                r.last_seen_at.isoformat() if r.last_seen_at else None
            )
            data["next_due"][key] = r.next_due_at.isoformat() if r.next_due_at else None
    return data
