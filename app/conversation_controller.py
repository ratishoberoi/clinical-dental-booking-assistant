from app.models import ConversationStage, SessionState
from app import session_store
from typing import Optional
from app.llm_engine import (
    generate_intake_question,
    extract_symptoms,
    handle_treatment_question,
    generate_pre_visit_instructions,
)
from app.specialty_router import get_specialties, get_urgency, get_urgency_prefix
from app.scheduler import (
    build_doctor_slot_display,
    get_doctor_slots_for_confirmation,
    confirm_booking,
    find_doctor_by_name,
    find_slot_by_day_time,
    get_doctor_by_id,
    get_slot_by_id,
)
from app.insurance_module import (
    parse_insurance_from_message,
    looks_like_provider,
    looks_like_policy_id,
    format_insurance_summary,
)

# ── Trigger words that mean user is asking for treatment advice ──
TREATMENT_QUESTION_TRIGGERS = [
    "what should", "what treatment", "how to fix", "what do i need",
    "what procedure", "what's wrong", "whats wrong", "diagnose",
    "what is it", "what could it be", "should i get", "do i need",
]

MAX_INTAKE_QUESTIONS = 3


def _is_treatment_question(message: str) -> bool:
    msg = message.lower()
    return any(trigger in msg for trigger in TREATMENT_QUESTION_TRIGGERS)


def process_message(session_id: str, user_message: str) -> str:
    """
    Main FSM dispatcher. Routes message to correct stage handler.
    All state transitions happen here — deterministic, no ambiguity.
    """
    session = session_store.get_or_create_session(session_id)

    # Log user message
    session_store.add_message(session, "user", user_message)

    # Extract and accumulate symptoms from every user message
    if session.stage in [ConversationStage.INTAKE, ConversationStage.TREATMENT_ROUTING]:
        new_symptoms = extract_symptoms(user_message)
        for s in new_symptoms:
            if s not in session.collected_symptoms and s not in ["[]", "", "none"]:
                session.collected_symptoms.append(s)
        session_store.update_session(session)

    # ── FSM Stage Router ──
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
        response = "Your appointment is already confirmed! Is there anything else you need help with?"

    else:
        response = "I'm sorry, something went wrong. Let me restart our conversation."
        session_store.advance_stage(session, ConversationStage.INTAKE)

    # Log assistant response
    session_store.add_message(session, "assistant", response)
    return response


# ─────────────────────────────────────────────────────────────
# STAGE 1: INTAKE
# Collect symptoms via smart LLM questions. Max 3 questions.
# ─────────────────────────────────────────────────────────────

def _handle_intake(session: SessionState, user_message: str) -> str:
    
    # If user is asking for treatment advice mid-intake, route immediately
    if _is_treatment_question(user_message) and len(session.collected_symptoms) >= 2:
        return _transition_to_treatment_routing(session)

    # Check if we have enough signal to stop asking
    # Lower threshold — if 3+ symptoms on first message, skip intake entirely
    enough_signal = (
        len(session.collected_symptoms) >= 3 or
        session.intake_questions_asked >= MAX_INTAKE_QUESTIONS
    )

    # Extra guard — if this is first message and already rich in symptoms, skip
    is_first_message = session.intake_questions_asked == 0
    rich_first_message = is_first_message and len(session.collected_symptoms) >= 3

    if enough_signal or rich_first_message:
        return _transition_to_treatment_routing(session)

    # Ask next smart intake question via LLM
    llm_response = generate_intake_question(
        session.conversation_history,
        session.collected_symptoms
    )

    # LLM signals it has enough info
    if "INTAKE_COMPLETE" in llm_response:
        return _transition_to_treatment_routing(session)

    session.intake_questions_asked += 1
    session_store.update_session(session)
    return llm_response


TIME_PREFERENCE_SIGNALS = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "mon", "tue", "wed", "thu", "fri", "sat", "sun",
    "morning", "afternoon", "evening", "night",
    "weekday", "weekend", "only do", "can do", "available", "free on",
    "am free", "i'm free", "prefer", "works for me", "only on"
]

def _extract_time_preference_from_history(session: SessionState) -> Optional[str]:
    """Check if user already mentioned time preference in any prior message."""
    for msg in session.conversation_history:
        if msg["role"] == "user":
            msg_lower = msg["content"].lower()
            matches = [sig for sig in TIME_PREFERENCE_SIGNALS if sig in msg_lower]
            if len(matches) >= 2:  # At least 2 signals = confident it's a preference
                return msg["content"]
    return None


def _transition_to_treatment_routing(session: SessionState) -> str:
    """Move from intake to specialty routing. Classify urgency here."""
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

    # Check if user already gave time preference — skip asking again
    existing_preference = _extract_time_preference_from_history(session)

    if existing_preference:
        # Auto-capture preference and jump straight to doctor display
        session.time_preference = existing_preference
        session_store.advance_stage(session, ConversationStage.DOCTOR_SLOT_DISPLAY)
        session_store.update_session(session)
        doctor_display = build_doctor_slot_display(specialties, existing_preference)
        return (
            f"{clinical_note}"
            f"I've noted your availability *(Tue/Thu evenings, Saturday)*. "
            f"Here are the matching doctors and slots:\n\n"
            f"{doctor_display}\n"
            f"Please reply with your preferred **doctor name** and **slot** "
            f"*(e.g. 'Dr. Mehta, Thursday 6:00 PM')*"
        )

    # No preference found — ask for it
    session_store.advance_stage(session, ConversationStage.TREATMENT_ROUTING)
    session_store.update_session(session)

    return (
        f"{clinical_note}"
        f"To schedule appropriately, what day or time range works best for you? "
        f"*(e.g. weekday evenings, Saturday mornings, Tuesday/Thursday)*"
    )


# ─────────────────────────────────────────────────────────────
# STAGE 2: TREATMENT ROUTING
# User may ask treatment questions here. Then capture time preference.
# ─────────────────────────────────────────────────────────────

def _handle_treatment_routing(session: SessionState, user_message: str) -> str:

    if _is_treatment_question(user_message):
        # LLM handles the clinical deflection
        response = handle_treatment_question(
            session.routed_specialties,
            session.collected_symptoms
        )
        # Still ask for time preference after deflection
        response += "\n\nTo move forward, what day or time range works best for you?"
        return response

    # User gave time preference — move to display
    return _handle_time_preference(session, user_message)


# ─────────────────────────────────────────────────────────────
# STAGE 3: TIME PREFERENCE
# Capture scheduling preference, then show doctors + slots.
# ─────────────────────────────────────────────────────────────

def _handle_time_preference(session: SessionState, user_message: str) -> str:
    session.time_preference = user_message
    session_store.advance_stage(session, ConversationStage.DOCTOR_SLOT_DISPLAY)
    session_store.update_session(session)

    return _build_and_display_doctors(session)


def _build_and_display_doctors(session: SessionState) -> str:
    doctor_display = build_doctor_slot_display(
        session.routed_specialties,
        session.time_preference or "any"
    )

    session_store.advance_stage(session, ConversationStage.DOCTOR_SELECTION)

    return (
        f"Here are the available doctors and slots matching your preference:\n\n"
        f"{doctor_display}\n"
        f"Please reply with your preferred **doctor name** and **slot** "
        f"*(e.g. 'Dr. Sharma, Tuesday 6:30 PM')*"
    )


# ─────────────────────────────────────────────────────────────
# STAGE 4: DOCTOR + SLOT DISPLAY → DOCTOR SELECTION
# User picks a doctor and slot. We validate against real DB.
# ─────────────────────────────────────────────────────────────

def _handle_doctor_slot_display(session: SessionState, user_message: str) -> str:
    # This stage transitions immediately after display — shouldn't land here
    # But guard it anyway
    return _handle_doctor_selection(session, user_message)


def _handle_doctor_selection(session: SessionState, user_message: str) -> str:
    # Try to find doctor from user message
    doctor = find_doctor_by_name(user_message)

    if not doctor:
        return (
            "I couldn't match that to a doctor in our system. "
            "Please reply with the doctor's name as shown above "
            "*(e.g. 'Dr. Sharma' or 'Dr. Mehta')*"
        )

    # Doctor found — store it
    session.booking.doctor_id = doctor["id"]
    session.booking.doctor_name = doctor["name"]
    session.booking.specialty = doctor["specialty"]

    # Try to extract slot from same message
    slot = find_slot_by_day_time(doctor["id"], user_message)

    if slot:
        session.booking.slot_id = slot["slot_id"]
        session.booking.slot_day = slot["day"]
        session.booking.slot_time = slot["time"]
        session_store.advance_stage(session, ConversationStage.INSURANCE_PROVIDER)
        session_store.update_session(session)
        return (
            f"Got it — **{doctor['name']}**, {slot['day']} at {slot['time']}.\n\n"
            f"Before confirming, do you have dental insurance? If yes, "
            f"please provide your **insurance provider name**."
        )

    # Doctor found but no slot in message — ask for slot separately
    slots = get_doctor_slots_for_confirmation(doctor["id"], session.time_preference or "any")

    if not slots:
        return (
            f"**{doctor['name']}** has no available slots matching your preference. "
            f"Please choose another doctor from the list above."
        )

    if len(slots) == 1:
        auto_slot = slots[0]
        session.booking.slot_id = auto_slot["slot_id"]
        session.booking.slot_day = auto_slot["day"]
        session.booking.slot_time = auto_slot["time"]
        session_store.advance_stage(session, ConversationStage.INSURANCE_PROVIDER)
        session_store.update_session(session)
        return (
            f"Great choice — **{doctor['name']}**. "
            f"Only one slot available: **{auto_slot['day']} at {auto_slot['time']}** — auto-selected.\n\n"
            f"Do you have dental insurance? If yes, provide your **insurance provider name**."
        )

    slot_strs = [f"{s['day']} at {s['time']}" for s in slots]
    slots_display = " | ".join(slot_strs)

    session_store.advance_stage(session, ConversationStage.SLOT_CONFIRMATION)
    session_store.update_session(session)

    return (
        f"Great choice — **{doctor['name']}**.\n\n"
        f"Available slots: {slots_display}\n\n"
        f"Which slot works for you?"
    )


# ─────────────────────────────────────────────────────────────
# STAGE 5: INSURANCE PROVIDER (Step 1 of 2)
# ─────────────────────────────────────────────────────────────

def _handle_insurance_provider(session: SessionState, user_message: str) -> str:
    msg_lower = user_message.lower().strip()

    # User has no insurance
    if any(word in msg_lower for word in ["no", "none", "don't", "dont", "nope", "uninsured", "no insurance"]):
        session.booking.insurance.provider = "None"
        session.booking.insurance.policy_id = "N/A"
        session_store.advance_stage(session, ConversationStage.SLOT_CONFIRMATION)
        session_store.update_session(session)
        return _build_slot_confirmation(session)

    # Try to parse provider (and maybe policy ID) from message
    FILLER_PHRASES = ["yes i have", "yes,", "i have", "my insurance is",
                      "it's", "its", "i use", "with", "provider is"]
    cleaned_message = user_message.lower().strip()
    for f in FILLER_PHRASES:
        cleaned_message = cleaned_message.replace(f, "").strip()
    # Restore proper casing for known providers
    for provider_name in ["Delta Dental", "Cigna", "Aetna", "MetLife",
                          "Guardian", "Humana", "United HealthCare", "Anthem",
                          "Blue Cross", "Blue Shield"]:
        if provider_name.lower() in cleaned_message:
            cleaned_message = provider_name
            break

    provider, policy_id = parse_insurance_from_message(cleaned_message)

    if provider:
        session.booking.insurance.provider = provider
        session_store.update_session(session)

        if policy_id:
            # Got both in one message — skip to confirmation
            session.booking.insurance.policy_id = policy_id
            session_store.advance_stage(session, ConversationStage.SLOT_CONFIRMATION)
            session_store.update_session(session)
            return _build_slot_confirmation(session)

        # Got provider only — ask for policy ID
        session_store.advance_stage(session, ConversationStage.INSURANCE_POLICY_ID)
        return (
            f"Got it — **{provider}**.\n\n"
            f"Please provide your **member ID or policy number**."
        )

    # Couldn't parse — re-ask
    return (
        "Could you please provide your insurance provider name? "
        "*(e.g. Delta Dental, Cigna, Aetna)*"
    )


# ─────────────────────────────────────────────────────────────
# STAGE 6: INSURANCE POLICY ID (Step 2 of 2)
# ─────────────────────────────────────────────────────────────

def _handle_insurance_policy_id(session: SessionState, user_message: str) -> str:
    from app.insurance_module import looks_like_policy_id
    policy_id = user_message.strip()

    if not policy_id:
        return "Please provide your member ID or policy number to proceed."

    # Validate format
    if not looks_like_policy_id(policy_id):
        return (
            f"That doesn't look like a valid member/policy ID.\n\n"
            f"Policy IDs are typically 5-20 characters and contain both "
            f"letters and numbers *(e.g. DDL-482920, UCH-29301A, CIG-10293B)*.\n\n"
            f"Please enter your correct member ID."
        )

    session.booking.insurance.policy_id = policy_id
    session_store.advance_stage(session, ConversationStage.SLOT_CONFIRMATION)
    session_store.update_session(session)

    return _build_slot_confirmation(session)


# ─────────────────────────────────────────────────────────────
# STAGE 7: SLOT CONFIRMATION
# Show full booking summary. User confirms.
# ─────────────────────────────────────────────────────────────

def _build_slot_confirmation(session: SessionState) -> str:
    b = session.booking
    insurance_line = (
        f"- Insurance: {b.insurance.provider} (ID: {b.insurance.policy_id})"
        if b.insurance.provider != "None"
        else "- Insurance: Self-pay / Uninsured"
    )

    return (
        f"Please confirm your appointment details:\n\n"
        f"- Doctor: **{b.doctor_name}**\n"
        f"- Specialty: {b.specialty}\n"
        f"- Slot: **{b.slot_day}** at **{b.slot_time}**\n"
        f"{insurance_line}\n\n"
        f"Reply **'confirm'** to book, or **'cancel'** to start over."
    )


def _handle_slot_confirmation(session: SessionState, user_message: str) -> str:
    msg_lower = user_message.lower().strip()

    # If slot not yet selected — try to parse slot from this message
    if not session.booking.slot_id and session.booking.doctor_id:
        slot = find_slot_by_day_time(session.booking.doctor_id, user_message)
        if slot:
            session.booking.slot_id = slot["slot_id"]
            session.booking.slot_day = slot["day"]
            session.booking.slot_time = slot["time"]
            session_store.update_session(session)
            return (
                f"Got it — **{session.booking.slot_day}** at **{session.booking.slot_time}**.\n\n"
                f"Do you have dental insurance? If yes, please provide your "
                f"**insurance provider name** *(e.g. Delta Dental, Cigna, Aetna)*"
            )
        else:
            # Slot not found — show real available slots
            slots = get_doctor_slots_for_confirmation(
                session.booking.doctor_id,
                session.time_preference or "any"
            )
            slot_strs = [f"{s['day']} at {s['time']}" for s in slots]
            return (
                f"I couldn't match that slot. Available slots for "
                f"**{session.booking.doctor_name}**: {' | '.join(slot_strs)}\n\n"
                f"Please choose one."
            )

    # Re-route to insurance if slot is set but insurance not captured
    if session.booking.slot_id and not session.booking.insurance.provider:
        session_store.advance_stage(session, ConversationStage.INSURANCE_PROVIDER)
        session_store.update_session(session)
        return (
            f"Do you have dental insurance? If yes, please provide your "
            f"**insurance provider name** *(e.g. Delta Dental, Cigna, Aetna)*"
        )

    if "confirm" in msg_lower:
        success = confirm_booking(session.booking.slot_id)

        if not success:
            return (
                "Sorry, that slot is no longer available. "
                "Please go back and choose another slot."
            )

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
            f"Please arrive 10 minutes early with your insurance card."
        )

    elif "cancel" in msg_lower or "start over" in msg_lower:
        session_store.reset_session(session.session_id)
        return (
            "Booking cancelled. Let's start fresh — "
            "please describe your dental concern."
        )

    else:
        return _build_slot_confirmation(session)