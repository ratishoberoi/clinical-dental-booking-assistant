from typing import Dict, Optional
from app.models import SessionState, ConversationStage, BookingDetails, InsuranceInfo
import uuid


# In-memory store — in production this would be Redis
_sessions: Dict[str, SessionState] = {}


def create_session() -> str:
    session_id = str(uuid.uuid4())
    _sessions[session_id] = SessionState(session_id=session_id)
    return session_id


def get_session(session_id: str) -> Optional[SessionState]:
    return _sessions.get(session_id)


def get_or_create_session(session_id: str) -> SessionState:
    if session_id not in _sessions:
        _sessions[session_id] = SessionState(session_id=session_id)
    return _sessions[session_id]


def update_session(session: SessionState) -> None:
    _sessions[session.session_id] = session


def advance_stage(session: SessionState, new_stage: ConversationStage) -> None:
    session.stage = new_stage
    update_session(session)


def add_message(session: SessionState, role: str, content: str) -> None:
    session.conversation_history.append({"role": role, "content": content})
    update_session(session)


def reset_session(session_id: str) -> str:
    _sessions[session_id] = SessionState(session_id=session_id)
    return session_id


def list_sessions() -> list:
    return [
        {
            "session_id": sid,
            "stage": s.stage,
            "symptoms_count": len(s.collected_symptoms),
            "booking_complete": s.stage == "booking_confirmed"
        }
        for sid, s in _sessions.items()
    ]