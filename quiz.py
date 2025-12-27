"""Quiz generation and mastery logic."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Set
from uuid import uuid4

from dotenv import load_dotenv

import db

if TYPE_CHECKING:  # pragma: no cover
    from openai import AzureOpenAI, OpenAIError  # type: ignore

load_dotenv()


def _client() -> Optional[AzureOpenAI]:
    try:
        from openai import AzureOpenAI  # type: ignore
    except ImportError:
        return None
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    key = os.getenv("AZURE_OPENAI_KEY")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
    if not endpoint or not key or not deployment:
        return None
    return AzureOpenAI(
        api_version="2024-02-01",
        azure_endpoint=endpoint,
        api_key=key,
    )


def _interval_days(score: float) -> int:
    if score >= 0.8:
        return 14
    if score >= 0.6:
        return 7
    if score >= 0.4:
        return 4
    if score >= 0.2:
        return 2
    return 1


def _fallback_questions(knowledge_items, family_members, n: int) -> List[Dict[str, Any]]:
    items = (knowledge_items + family_members)[:n]
    questions = []
    for item in items:
        questions.append(
            {
                "id": str(uuid4()),
                "question_type": "mcq",
                "prompt": f"Who/What is {item.get('label') or item.get('full_name')}?",
                "options": [item.get("value") or item.get("full_name"), "Not sure"],
                "correct_answer": item.get("value") or item.get("full_name"),
                "item_type": "knowledge" if "label" in item else "family",
                "item_id": item["id"],
                "difficulty": 1,
                "acceptable_answers": [],
            }
        )
    return questions


def generate_quiz_questions(
    patient: Dict[str, Any],
    family_members: List[Dict[str, Any]],
    knowledge_items: List[Dict[str, Any]],
    due_items: List[Dict[str, Any]],
    n: int = 7,
    include_sensitive: bool = False,
) -> List[Dict[str, Any]]:
    sensitive_filtered = [
        ki
        for ki in knowledge_items
        if include_sensitive or int(ki.get("sensitivity_level", 0)) < 2
    ]
    selected_items: List[Dict[str, Any]] = []
    knowledge_lookup = {k["id"]: k for k in sensitive_filtered}
    family_lookup = {f["id"]: f for f in family_members}
    seen: Set[str] = set()

    # prioritize due items
    for due in due_items:
        item = None
        if due.get("item_type") == "knowledge":
            item = knowledge_lookup.get(due.get("item_id"))
        elif due.get("item_type") == "family":
            item = family_lookup.get(due.get("item_id"))
        if item and item["id"] not in seen:
            selected_items.append(item)
            seen.add(item["id"])

    # fill remaining slots
    for item in sensitive_filtered + family_members:
        if item["id"] in seen:
            continue
        selected_items.append(item)
        seen.add(item["id"])
        if len(selected_items) >= n:
            break

    items_pool = selected_items[:n]
    client = _client()
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
    if not client or not deployment:
        return _fallback_questions(items_pool, [], n)
    try:
        from openai import OpenAIError  # type: ignore
    except ImportError:  # pragma: no cover
        OpenAIError = Exception  # type: ignore
    prompt = (
        "You are generating gentle quiz questions for dementia care. "
        "Use ONLY provided facts. Respond with JSON matching the schema: "
        '{"questions":[{"question_type":"mcq|recall|photo_identity|true_false",'
        '"prompt":"string","options":["string"...],"correct_answer":"string|number|boolean",'
        '"item_type":"knowledge|family","item_id":"uuid","difficulty":1,"acceptable_answers":["string"...]}]}'
    )
    messages = [
        {
            "role": "system",
            "content": prompt,
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "patient": {"full_name": patient.get("full_name")},
                    "family_members": family_members,
                    "knowledge_items": sensitive_filtered,
                    "due_items": due_items,
                    "n": n,
                }
            ),
        },
    ]
    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=messages,
            temperature=0.2,
            max_tokens=1200,
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        return data.get("questions", [])
    except (OpenAIError, json.JSONDecodeError):
        return _fallback_questions(items_pool, [], n)


def evaluate_answer(
    question_type: str,
    correct_answer: Any,
    user_answer: Any,
    acceptable_answers: Optional[List[str]] = None,
) -> bool:
    acceptable_answers = acceptable_answers or []
    if question_type == "recall":
        ua = str(user_answer).strip().lower()
        if str(correct_answer).strip().lower() == ua:
            return True
        return ua in [a.lower() for a in acceptable_answers]
    return str(user_answer).strip().lower() == str(correct_answer).strip().lower()


def compute_mastery_update(
    engine,
    patient_id: str,
    payload: Dict[str, Any],
    correct: bool,
    response_time_ms: int,
):
    item_type = payload.get("item_type")
    item_id = payload.get("item_id")
    if not item_type or not item_id:
        return None
    existing = db._get_mastery_row(engine, patient_id, item_type, item_id)  # type: ignore
    mastery_score = float(existing["mastery_score"]) if existing else 0.0
    consecutive_correct = int(existing["consecutive_correct"]) if existing else 0
    consecutive_incorrect = int(existing["consecutive_incorrect"]) if existing else 0
    if correct:
        consecutive_correct += 1
        consecutive_incorrect = 0
        mastery_score = min(1.0, mastery_score + 0.1)
        if response_time_ms < 3000:
            mastery_score = min(1.0, mastery_score + 0.05)
    else:
        consecutive_incorrect += 1
        consecutive_correct = 0
        mastery_score = max(0.0, mastery_score - 0.05)
    days = _interval_days(mastery_score)
    next_due = datetime.utcnow() + timedelta(days=days)
    return {
        "patient_id": patient_id,
        "item_type": item_type,
        "item_id": item_id,
        "mastery_score": mastery_score,
        "consecutive_correct": consecutive_correct,
        "consecutive_incorrect": consecutive_incorrect,
        "last_seen_at": datetime.utcnow(),
        "next_due_at": next_due,
    }
