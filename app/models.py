from pydantic import BaseModel
from typing import Optional, List
from enum import Enum


class ConversationStage(str, Enum):
    INTAKE = "intake"
    TREATMENT_ROUTING = "treatment_routing"
    TIME_PREFERENCE = "time_preference"
    DOCTOR_SLOT_DISPLAY = "doctor_slot_display"
    DOCTOR_SELECTION = "doctor_selection"
    INSURANCE_PROVIDER = "insurance_provider"
    INSURANCE_POLICY_ID = "insurance_policy_id"
    SLOT_CONFIRMATION = "slot_confirmation"
    BOOKING_CONFIRMED = "booking_confirmed"


class ChatRequest(BaseModel):
    session_id: str
    user_message: str


class ChatResponse(BaseModel):
    session_id: str
    assistant_message: str
    current_stage: str
    booking_complete: bool = False


class InsuranceInfo(BaseModel):
    provider: Optional[str] = None
    policy_id: Optional[str] = None


class BookingDetails(BaseModel):
    specialty: Optional[str] = None
    doctor_id: Optional[str] = None
    doctor_name: Optional[str] = None
    slot_id: Optional[str] = None
    slot_day: Optional[str] = None
    slot_time: Optional[str] = None
    insurance: InsuranceInfo = InsuranceInfo()


class SessionState(BaseModel):
    session_id: str
    stage: ConversationStage = ConversationStage.INTAKE
    conversation_history: List[dict] = []
    collected_symptoms: List[str] = []
    intake_questions_asked: int = 0
    time_preference: Optional[str] = None
    routed_specialties: List[str] = []
    booking: BookingDetails = BookingDetails()
    pre_visit_instructions_sent: bool = False