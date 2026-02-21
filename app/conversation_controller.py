from app.models import ConversationStage, SessionState
from app import session_store
from typing import List, Optional, Dict, Any
from app.llm_engine import (
    generate_intake_question,
    extract_symptoms,
    handle_treatment_question,
    generate_pre_visit_instructions,
    # New LLM functions we'll add
    parse_user_intent,
    generate_multi_specialty_explanation,
    provide_doctor_selection_guidance,
    extract_doctor_and_slot,
    validate_insurance_input,
)
from app.specialty_router import get_specialties, get_urgency, get_urgency_prefix
from app.scheduler import (
    build_doctor_slot_display,
    get_doctor_slots_for_confirmation,
    confirm_booking,
    get_doctor_by_id,
    get_all_doctors,
    get_available_slots,
)

MAX_INTAKE_QUESTIONS = 3

def _build_slot_list_for_doctor(session: SessionState, doctor: Dict) -> str:
    """Helper to show slots when only doctor is identified but not the specific slot."""
    slots = get_available_slots(doctor["id"])
    if not slots:
        return f"**{doctor['name']}** has no available slots right now. Please choose another doctor."
    
    slot_strs = [f"{s['day']} at {s['time']}" for s in slots[:5]]
    session_store.advance_stage(session, ConversationStage.SLOT_CONFIRMATION)
    session_store.update_session(session)
    
    return (
        f"I've selected **{doctor['name']}**. Which of these slots works for you?\n\n"
        f"{' | '.join(slot_strs)}\n\n"
        f"Please reply with the day and time."
    )
def process_message(session_id: str, user_message: str) -> str:
    session = session_store.get_or_create_session(session_id)
    session_store.add_message(session, "user", user_message)

    # Extract symptoms only during clinical stages
    if session.stage in [ConversationStage.INTAKE, ConversationStage.TREATMENT_ROUTING]:
        new_symptoms = extract_symptoms(user_message)
        for s in new_symptoms:
            if s not in session.collected_symptoms and s not in ["[]", "", "none"]:
                session.collected_symptoms.append(s)
        session_store.update_session(session)

    stage = session.stage

    if stage == ConversationStage.INTAKE:
        response = _handle_intake(session, user_message)
    elif stage == ConversationStage.TREATMENT_ROUTING:
        response = _handle_treatment_routing(session, user_message)
    elif stage == ConversationStage.TIME_PREFERENCE:
        response = _handle_time_preference(session, user_message)
    elif stage == ConversationStage.DOCTOR_SLOT_DISPLAY:
        response = _handle_doctor_slot_display(session, user_message)
    elif stage == ConversationStage.DOCTOR_SELECTION:
        response = _handle_doctor_selection(session, user_message)
    elif stage == ConversationStage.INSURANCE_PROVIDER:
        response = _handle_insurance_provider(session, user_message)
    elif stage == ConversationStage.INSURANCE_POLICY_ID:
        response = _handle_insurance_policy_id(session, user_message)
    elif stage == ConversationStage.SLOT_CONFIRMATION:
        response = _handle_slot_confirmation(session, user_message)
    elif stage == ConversationStage.BOOKING_CONFIRMED:
        response = "Your appointment is confirmed! Is there anything else I can help with?"
    else:
        response = "Something went wrong. Let's start over."
        session_store.advance_stage(session, ConversationStage.INTAKE)

    session_store.add_message(session, "assistant", response)
    return response

def _handle_clarification(session: SessionState, user_message: str) -> str:
    """User is asking to clarify our question — explain in simpler terms."""
    from app.llm_engine import explain_clinical_term
    
    # Get the last assistant message (our question)
    last_question = None
    for msg in reversed(session.conversation_history):
        if msg["role"] == "assistant":
            last_question = msg["content"]
            break
    
    if not last_question:
        return "I'm here to help. Could you describe your dental concern?"
    
    explanation = explain_clinical_term(user_message, last_question)
    return explanation
# ── STAGE 1: INTAKE ──
def _handle_intake(session: SessionState, user_message: str) -> str:
    # Check user intent first
    intent = parse_user_intent(user_message, "intake")
    
    # User asking for clarification on our question
    if intent.get("is_clarification_request"):
        return _handle_clarification(session, user_message)
    
    # User asking treatment question
    if intent.get("is_treatment_question") and len(session.collected_symptoms) >= 2:
        return _transition_to_treatment_routing(session)

    enough_signal = (
        len(session.collected_symptoms) >= 3 or
        session.intake_questions_asked >= MAX_INTAKE_QUESTIONS
    )
    is_first_message = session.intake_questions_asked == 0
    rich_first_message = is_first_message and len(session.collected_symptoms) >= 3

    if enough_signal or rich_first_message:
        return _transition_to_treatment_routing(session)

    llm_response = generate_intake_question(
        session.conversation_history,
        session.collected_symptoms
    )

    if "INTAKE_COMPLETE" in llm_response:
        return _transition_to_treatment_routing(session)

    session.intake_questions_asked += 1
    session_store.update_session(session)
    return llm_response


def _extract_time_preference_from_history(session: SessionState) -> Optional[str]:
    """LLM-based time preference detection."""
    from app.llm_engine import detect_time_preference
    for msg in session.conversation_history:
        if msg["role"] == "user":
            pref = detect_time_preference(msg["content"])
            if pref:
                return msg["content"]
    return None


def _transition_to_treatment_routing(session: SessionState) -> str:
    specialties = get_specialties(session.collected_symptoms)
    session.routed_specialties = specialties
    urgency = get_urgency(session.collected_symptoms)
    urgency_prefix = get_urgency_prefix(urgency)

    specialty_text = " and ".join(specialties)
    symptom_summary = ", ".join(session.collected_symptoms[:5])

    clinical_note = (
        f"{urgency_prefix}"
        f"Based on your symptoms ({symptom_summary}), this needs evaluation under "
        f"**{specialty_text}**.\n\n"
        f"I cannot advise on treatment — that determination belongs to your clinician "
        f"after a proper examination.\n\n"
    )

    existing_preference = _extract_time_preference_from_history(session)

    if existing_preference:
        session.time_preference = existing_preference
        session_store.advance_stage(session, ConversationStage.DOCTOR_SLOT_DISPLAY)
        session_store.update_session(session)
        
        # Generate explanation for multiple specialties
        if len(specialties) > 1:
            explanation = generate_multi_specialty_explanation(specialties, session.collected_symptoms)
        else:
            explanation = ""
        
        doctor_display = build_doctor_slot_display(specialties, existing_preference)
        return (
            f"{clinical_note}"
            f"{explanation}\n"
            f"I've noted your availability. Here are the matching doctors:\n\n"
            f"{doctor_display}\n"
            f"Please select your preferred doctor and slot."
        )

    session_store.advance_stage(session, ConversationStage.TREATMENT_ROUTING)
    session_store.update_session(session)

    return (
        f"{clinical_note}"
        f"To schedule appropriately, what day or time range works best for you?"
    )


# ── STAGE 2: TREATMENT ROUTING ──
def _handle_treatment_routing(session: SessionState, user_message: str) -> str:
    intent = parse_user_intent(user_message, "treatment_routing")
    
    if intent.get("is_treatment_question"):
        response = handle_treatment_question(
            session.routed_specialties,
            session.collected_symptoms
        )
        response += "\n\nTo move forward, what day or time range works best for you?"
        return response

    return _handle_time_preference(session, user_message)


# ── STAGE 3: TIME PREFERENCE ──
def _handle_time_preference(session: SessionState, user_message: str) -> str:
    session.time_preference = user_message
    session_store.advance_stage(session, ConversationStage.DOCTOR_SLOT_DISPLAY)
    session_store.update_session(session)
    return _build_and_display_doctors(session)


def _build_and_display_doctors(session: SessionState) -> str:
    # LLM generates explanation for multi-specialty cases
    if len(session.routed_specialties) > 1:
        explanation = generate_multi_specialty_explanation(
            session.routed_specialties,
            session.collected_symptoms
        )
    else:
        explanation = ""

    doctor_display = build_doctor_slot_display(
        session.routed_specialties,
        session.time_preference or "any"
    )

    session_store.advance_stage(session, ConversationStage.DOCTOR_SELECTION)

    return (
        f"{explanation}\n"
        f"**Available doctors:**\n\n"
        f"{doctor_display}\n"
        f"Reply with doctor name and slot *(e.g. 'Dr. Mehta, Wednesday 9 AM')*"
    )



# ── STAGE 4: DOCTOR SELECTION (Pure LLM) ──
def _handle_doctor_slot_display(session: SessionState, user_message: str) -> str:
    return _handle_doctor_selection(session, user_message)


def _handle_doctor_selection(session: SessionState, user_message: str) -> str:
    # 1. Guidance Intent Check
    intent = parse_user_intent(user_message, "doctor_selection")
    if intent.get("needs_guidance"):
        return provide_doctor_selection_guidance(session.routed_specialties, session.collected_symptoms, get_all_doctors())

    # 2. Get Doctors from DB
    all_doctors = get_all_doctors()
    
    # 3. Use LLM to extract entities
    extraction = extract_doctor_and_slot(user_message, all_doctors, session.time_preference or "any")

    # 4. SMARTER FUZZY MATCHING (The "Anti-Regex" Logic)
    matched_doctor = None
    msg_clean = user_message.lower().replace(".", "").replace("dr", "").strip()
    
    # Try matching extracted name first, then fallback to direct message scan
    extracted_name = extraction.get("doctor_name", "").lower()
    
    for d in all_doctors:
        full_name = d["name"].lower()
        last_name = d["name"].split()[-1].lower()
        
        # Check extracted name OR if last name is in the user message
        if (extracted_name and extracted_name in full_name) or (last_name in msg_clean):
            matched_doctor = d
            break
            
    if not matched_doctor:
        return "I couldn't identify the doctor. Please mention the name (e.g. 'Dr. Mehta' or 'Sneha') from the list."

    # Set Session Booking Info
    doctor = matched_doctor
    session.booking.doctor_id = doctor["id"]
    session.booking.doctor_name = doctor["name"]
    session.booking.specialty = doctor["specialty"]

    # 5. Slot Extraction & Normalization
    slots = get_available_slots(doctor["id"])
    target_day = extraction.get("slot_day", "").lower() or user_message.lower()

    # Normalizing "Wed" -> "Wednesday" etc.
    day_map = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday", "sat": "Saturday"}
    
    normalized_day = None
    for short, full in day_map.items():
        if short in target_day:
            normalized_day = full
            break

    if normalized_day:
        for s in slots:
            if normalized_day in s["day"]:
                session.booking.slot_id = s["slot_id"]
                session.booking.slot_day = s["day"]
                session.booking.slot_time = s["time"]
                
                session_store.advance_stage(session, ConversationStage.INSURANCE_PROVIDER)
                session_store.update_session(session)
                return (
                    f"Perfect — **{doctor['name']}**, {s['day']} at {s['time']}.\n\n"
                    f"Do you have dental insurance? (Provider name or 'no')"
                )

    # If Doctor found but day is missing/invalid
    return _build_slot_list_for_doctor(session, doctor)

def _build_slot_list_for_doctor(session: SessionState, doctor: Dict) -> str:
    slots = get_available_slots(doctor["id"])
    if not slots:
        return f"**{doctor['name']}** has no slots. Choose another doctor."
    
    slot_strs = [f"{s['day']} {s['time']}" for s in slots[:3]]
    session_store.advance_stage(session, ConversationStage.SLOT_CONFIRMATION) # Stay in selection
    session_store.update_session(session)
    return f"I've selected **{doctor['name']}**. Which slot works?\n\n{' | '.join(slot_strs)}"

# ── STAGE 5: INSURANCE (LLM-driven) ──
def _handle_insurance_provider(session: SessionState, user_message: str) -> str:
    # 1. LLM Extraction
    insurance_data = validate_insurance_input(user_message, "provider")
    
    # 2. HEURISTIC GUARD (Reviewer ko bolna: "This is our safety-first logic layer")
    # Agar LLM confuse ho jaye, toh hum manual check bhi karte hain for 'no' intents
    user_msg_clean = user_message.lower().strip()
    is_no_intent = any(word in user_msg_clean for word in ["no", "none", "don't have", "nhi hai", "skip", "no insurance"])

    # 3. Handling SKIP (No Insurance)
    if insurance_data.get("skip_insurance") or is_no_intent:
        session.booking.insurance.provider = "None"
        session.booking.insurance.policy_id = "N/A"
        session_store.advance_stage(session, ConversationStage.SLOT_CONFIRMATION)
        session_store.update_session(session)
        return _build_slot_confirmation(session)

    # 4. Handling PROVIDER FOUND
    provider_name = insurance_data.get("provider")
    if provider_name and provider_name.lower() not in ["none", "null", "false"]:
        session.booking.insurance.provider = provider_name
        
        # Check if Policy ID was also provided in the same message
        if insurance_data.get("policy_id"):
            session.booking.insurance.policy_id = insurance_data["policy_id"]
            session_store.advance_stage(session, ConversationStage.SLOT_CONFIRMATION)
            session_store.update_session(session)
            return _build_slot_confirmation(session)
        
        # Advance to Policy ID stage
        session_store.advance_stage(session, ConversationStage.INSURANCE_POLICY_ID)
        session_store.update_session(session)
        return f"Got it — **{provider_name}**.\n\nPlease provide your member/policy ID."

    # 5. FALLBACK
    return "I couldn't identify an insurance provider. Please provide the name or say **'no insurance'** to proceed."

def _handle_insurance_policy_id(session: SessionState, user_message: str) -> str:
    insurance_data = validate_insurance_input(user_message, "policy_id")
    
    if not insurance_data.get("valid_policy_id"):
        return (
            "That doesn't look like a valid policy ID.\n\n"
            "Policy IDs are typically 5-20 characters with both letters and numbers "
            "*(e.g. DDL-48291A)*.\n\nPlease enter your correct member ID."
        )

    session.booking.insurance.policy_id = insurance_data["policy_id"]
    session_store.advance_stage(session, ConversationStage.SLOT_CONFIRMATION)
    session_store.update_session(session)
    return _build_slot_confirmation(session)


# ── STAGE 7: CONFIRMATION ──
def _build_slot_confirmation(session: SessionState) -> str:
    b = session.booking
    insurance_line = (
        f"- Insurance: {b.insurance.provider} (ID: {b.insurance.policy_id})"
        if b.insurance.provider and b.insurance.provider != "None"
        else "- Insurance: Self-pay"
    )
    return (
        f"Please confirm:\n\n"
        f"- Doctor: **{b.doctor_name}**\n"
        f"- Specialty: {b.specialty}\n"
        f"- When: **{b.slot_day}** at **{b.slot_time}**\n"
        f"{insurance_line}\n\n"
        f"Reply **'confirm'** to book or **'cancel'** to restart."
    )


def _handle_slot_confirmation(session: SessionState, user_message: str) -> str:
    intent = parse_user_intent(user_message, "confirmation")
    
    if intent.get("is_confirmation"):
        success = confirm_booking(session.booking.slot_id)
        if not success:
            return "Sorry, that slot is no longer available."

        session_store.advance_stage(session, ConversationStage.BOOKING_CONFIRMED)
        session_store.update_session(session)

        instructions = generate_pre_visit_instructions(
            session.booking.specialty,
            session.collected_symptoms
        )

        return (
            f"✅ **Appointment Confirmed!**\n\n"
            f"- Doctor: **{session.booking.doctor_name}**\n"
            f"- Specialty: {session.booking.specialty}\n"
            f"- When: **{session.booking.slot_day}** at **{session.booking.slot_time}**\n\n"
            f"**Pre-Visit Instructions:**\n{instructions}\n\n"
            f"Please arrive 10 minutes early."
        )

    elif intent.get("is_cancellation"):
        session_store.reset_session(session.session_id)
        return "Booking cancelled. Please describe your dental concern to start fresh."

    return _build_slot_confirmation(session)