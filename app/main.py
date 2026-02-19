from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.models import ChatRequest, ChatResponse
from app.models import ConversationStage
from app.conversation_controller import process_message
from app import session_store
import uuid

app = FastAPI(
    title="Clinical Dental Booking Assistant",
    description="AI-driven dental triage and appointment scheduling system",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "running", "service": "Dental Booking Assistant API"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/session/new")
def new_session():
    """Create a new conversation session."""
    session_id = str(uuid.uuid4())
    session_store.get_or_create_session(session_id)
    return {
        "session_id": session_id,
        "message": "Session created. Send your dental concern to /chat"
    }


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """Main chat endpoint. Processes user message and returns assistant response."""
    if not request.user_message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        response_text = process_message(request.session_id, request.user_message)
        session = session_store.get_session(request.session_id)

        return ChatResponse(
            session_id=request.session_id,
            assistant_message=response_text,
            current_stage=session.stage if session else "unknown",
            booking_complete=session.stage == ConversationStage.BOOKING_CONFIRMED if session else False
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/session/{session_id}")
def get_session_info(session_id: str):
    """Inspect session state — useful for debugging."""
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id,
        "stage": session.stage,
        "collected_symptoms": session.collected_symptoms,
        "routed_specialties": session.routed_specialties,
        "intake_questions_asked": session.intake_questions_asked,
        "time_preference": session.time_preference,
        "booking": session.booking.dict(),
        "conversation_turns": len(session.conversation_history)
    }


@app.get("/sessions")
def list_all_sessions():
    """List all active sessions."""
    return {"sessions": session_store.list_sessions()}


@app.delete("/session/{session_id}/reset")
def reset_session(session_id: str):
    """Reset a session back to intake stage."""
    session_store.reset_session(session_id)
    return {"message": f"Session {session_id} reset successfully"}
