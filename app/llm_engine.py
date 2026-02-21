import os
from openai import OpenAI
from groq import Groq
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile" 


def _chat(messages: List[dict], temperature: float = 0.3) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=512,
        extra_headers={
            "HTTP-Referer": "http://localhost:8501",
            "X-Title": "Dental Booking Assistant"
        }
    )
    return response.choices[0].message.content.strip()


# ─────────────────────────────────────────────
# MODULE 1: Clinical Intake Question Generator
# ─────────────────────────────────────────────

INTAKE_SYSTEM_PROMPT = """You are a clinical dental triage assistant with deep knowledge of dental pathology.

Your job is to ask ONE smart, high-value clinical follow-up question to build a complete symptom picture.

Rules:
- Read the full conversation history carefully
- NEVER ask about something already mentioned by the patient
- NEVER ask obvious follow-ups
- NEVER ask permission questions like "would you like to book?" or "should I schedule?"
- Ask only about: onset, triggers, duration, swelling, night pain, lingering cold/hot sensitivity, trauma, prior treatment
- If the patient has mentioned 2 or more of these: pain type, sensitivity, swelling, impacted tooth, cosmetic goal, timeline — respond with exactly: INTAKE_COMPLETE
- If patient described 3+ symptoms in first message — respond with exactly: INTAKE_COMPLETE
- Keep question clinical but conversational — one sentence only
- Do not explain why you're asking"""

def generate_intake_question(conversation_history: List[dict], collected_symptoms: List[str]) -> str:
    symptoms_context = f"Already known symptoms: {', '.join(collected_symptoms)}" if collected_symptoms else "No symptoms collected yet."

    messages = [
        {"role": "system", "content": INTAKE_SYSTEM_PROMPT},
        {"role": "user", "content": f"{symptoms_context}\n\nConversation so far:\n" +
            "\n".join([f"{m['role'].upper()}: {m['content']}" for m in conversation_history[-6:]])
        }
    ]
    return _chat(messages, temperature=0.2)


# ─────────────────────────────────────────────
# MODULE 2: Symptom Extractor
# ─────────────────────────────────────────────

SYMPTOM_EXTRACT_PROMPT = """You are a dental clinical data extractor.

From the patient's message, extract ALL symptoms or clinical facts mentioned.
Return them as a simple comma-separated list of short clinical phrases.

Examples:
- Input: "I have severe pain at night and it hurts with cold drinks"
- Output: severe night pain, cold sensitivity

- Input: "my wisdom tooth is impacted and I want aligners before my wedding"
- Output: impacted wisdom tooth, aligner treatment goal, wedding timeline constraint

Only return the comma-separated list. No explanations. No bullet points."""
def extract_symptoms(user_message: str) -> List[str]:
    messages = [
        {"role": "system", "content": SYMPTOM_EXTRACT_PROMPT},
        {"role": "user", "content": user_message}
    ]
    result = _chat(messages, temperature=0.1).strip()
    
    # Guard: LLM returned empty list notation or nothing useful
    if not result or result in ["[]", "none", "None", "N/A", "n/a", "-"]:
        return []
    
    # Guard: strip any accidental brackets LLM adds
    result = result.strip("[]").strip()
    
    JUNK_PHRASES = [
        "yesterday", "today", "started", "onset", "ago", "days ago",
        "post-procedure", "follow-up", "current symptoms", "none", "n/a",
        "it started", "began", "since"
    ]

    # Handle LLM returning bullet points or numbered lists instead of CSV
    if "\n" in result and "," not in result:
        lines = result.split("\n")
        parsed = []
        for line in lines:
            line = line.strip().lstrip("-*•123456789. ").strip()
            if line and len(line) > 2:
                # Filter junk
                if not any(junk in line.lower() for junk in JUNK_PHRASES):
                    parsed.append(line)
        return parsed

    parsed = [
        s.strip() for s in result.split(",")
        if s.strip()
        and len(s.strip()) > 2
        and not any(junk in s.lower() for junk in JUNK_PHRASES)
    ]
    return parsed


# ─────────────────────────────────────────────
# MODULE 3: Specialty Router (AI-driven)
# ─────────────────────────────────────────────

SPECIALTY_ROUTER_PROMPT = """You are a senior dental triage specialist who routes patients to the correct specialty.

Available specialties:
- Endodontics (root canals, pulp issues: lingering cold/hot pain, spontaneous pain, night pain, abscess)
- Oral Surgery (extractions, impacted wisdom teeth, jaw issues, trauma, implants)
- Orthodontics (braces, aligners, Invisalign, bite alignment, cosmetic straightening)
- Periodontics (gum disease, gum recession, bleeding gums, gum swelling)
- Restorative Dentistry (crowns, fillings, broken teeth, missing teeth, crown came off)

Rules:
- A patient may need MORE THAN ONE specialty — list all that apply
- Base your decision on symptom clustering, NOT keyword matching
- Return ONLY a JSON array of specialty names, nothing else

Example outputs:
["Endodontics"]
["Endodontics", "Oral Surgery"]
["Orthodontics", "Oral Surgery"]"""

def route_to_specialties(collected_symptoms: List[str]) -> List[str]:
    symptom_text = ", ".join(collected_symptoms)
    messages = [
        {"role": "system", "content": SPECIALTY_ROUTER_PROMPT},
        {"role": "user", "content": f"Patient symptoms: {symptom_text}"}
    ]
    result = _chat(messages, temperature=0.1)
    import json
    try:
        specialties = json.loads(result)
        return specialties if isinstance(specialties, list) else [result]
    except Exception:
        return [result.strip()]


# ─────────────────────────────────────────────
# MODULE 4: Urgency Classifier
# ─────────────────────────────────────────────

URGENCY_PROMPT = """You are a dental urgency classifier.

Classify the urgency of the patient's condition as one of:
- EMERGENCY (severe uncontrolled pain, swelling spreading to face/neck, trauma with bleeding)
- URGENT (significant pain, infection signs, lost crown, impacted tooth with acute pain)
- ROUTINE (cosmetic, elective, mild discomfort, planning ahead)

Return ONLY one word: EMERGENCY, URGENT, or ROUTINE."""

def classify_urgency(collected_symptoms: List[str]) -> str:
    symptom_text = ", ".join(collected_symptoms)
    messages = [
        {"role": "system", "content": URGENCY_PROMPT},
        {"role": "user", "content": f"Patient symptoms: {symptom_text}"}
    ]
    result = _chat(messages, temperature=0.1)
    result = result.strip().upper()
    if result in ["EMERGENCY", "URGENT", "ROUTINE"]:
        return result
    return "URGENT"


# ─────────────────────────────────────────────
# MODULE 5: Pre-Visit Instructions Generator
# ─────────────────────────────────────────────

PRE_VISIT_PROMPT = """You are a dental clinical coordinator giving pre-visit instructions.

Based on the specialty, give 2-3 specific, actionable pre-visit instructions.
Keep it concise, clinical, and helpful.
Do NOT say "good luck" or generic phrases.
Format as a short numbered list."""

def generate_pre_visit_instructions(specialty: str, symptoms: List[str]) -> str:
    symptom_text = ", ".join(symptoms)
    messages = [
        {"role": "system", "content": PRE_VISIT_PROMPT},
        {"role": "user", "content": f"Specialty: {specialty}\nPatient symptoms: {symptom_text}"}
    ]
    return _chat(messages, temperature=0.3)


# ─────────────────────────────────────────────
# MODULE 6: Treatment Question Handler
# ─────────────────────────────────────────────

TREATMENT_HANDLER_PROMPT = """You are a dental triage assistant. A patient is asking what treatment they need.

You must:
1. Decline to give treatment advice (you are not the treating dentist)
2. Tell them their symptoms suggest evaluation under a specific specialty
3. Move the conversation forward — do NOT ask "would you like to book?"

Be direct, clinical, and confident. 2-3 sentences max."""

def handle_treatment_question(specialties: List[str], symptoms: List[str]) -> str:
    specialty_text = " and ".join(specialties)
    symptom_text = ", ".join(symptoms)
    messages = [
        {"role": "system", "content": TREATMENT_HANDLER_PROMPT},
        {"role": "user", "content": f"Patient symptoms: {symptom_text}\nRouted specialties: {specialty_text}"}
    ]
    return _chat(messages, temperature=0.3)

# ─────────────────────────────────────────────
# MODULE 7: Intent Parser (Pure LLM)
# ─────────────────────────────────────────────

INTENT_PARSE_PROMPT = """You are analyzing user intent in a dental booking conversation.

Stage: {stage}
User message: "{message}"

Determine the user's intent and return ONLY a JSON object:
{{
  "is_treatment_question": bool,
  "needs_guidance": bool,
  "is_confirmation": bool,
  "is_cancellation": bool,
  "is_clarification_request": bool
}}

is_clarification_request = true when user asks "what do you mean?", "what is X?", "can you explain?", etc.

Examples:
- "what treatment do I need?" → {{"is_treatment_question": true}}
- "whom should I opt for?" → {{"needs_guidance": true}}
- "confirm" → {{"is_confirmation": true}}
- "cancel" → {{"is_cancellation": true}}

Return ONLY the JSON, no explanation."""

def parse_user_intent(user_message: str, stage: str) -> Dict[str, Any]:
    prompt = INTENT_PARSE_PROMPT.format(stage=stage, message=user_message)
    messages = [{"role": "user", "content": prompt}]
    result = _chat(messages, temperature=0.1)
    
    import json
    try:
        return json.loads(result.strip().strip("`").replace("```json", "").replace("```", ""))
    except:
        return {}


# ─────────────────────────────────────────────
# MODULE 8: Time Preference Detector
# ─────────────────────────────────────────────

def detect_time_preference(message: str) -> Optional[str]:
    prompt = f"""Does this message mention a time preference for scheduling?

Message: "{message}"

If YES, return the time preference phrase.
If NO, return exactly: NONE

Examples:
- "I'm free Saturday" → "Saturday"
- "I can only do Tuesday evenings" → "Tuesday evenings"
- "tomorrow" → "tomorrow"
- "I have severe pain" → NONE"""

    messages = [{"role": "user", "content": prompt}]
    result = _chat(messages, temperature=0.1)
    
    if "NONE" in result:
        return None
    
    # Parse relative time
    parsed = parse_relative_time(result.strip())
    return parsed


# ─────────────────────────────────────────────
# MODULE 9: Multi-Specialty Explainer
# ─────────────────────────────────────────────

MULTI_SPECIALTY_PROMPT = """Patient needs: {specialties}
Symptoms: {symptoms}

Write 2 sentences:
1. WHY each specialty is needed (brief reason)
2. Which to prioritize and WHY

Format:
💡 **You need:**
- **[Specialty 1]** for [reason]
- **[Specialty 2]** for [reason]

**Start with [Priority Specialty]** — [why prioritize this one].

Be concise but informative."""

def generate_multi_specialty_explanation(specialties: List[str], symptoms: List[str]) -> str:
    if len(specialties) == 1:
        return ""
    
    prompt = MULTI_SPECIALTY_PROMPT.format(
        specialties=", ".join(specialties),
        symptoms=", ".join(symptoms)
    )
    messages = [{"role": "user", "content": prompt}]
    return _chat(messages, temperature=0.3) + "\n\n"


# ─────────────────────────────────────────────
# MODULE 10: Doctor Selection Guidance
# ─────────────────────────────────────────────

GUIDANCE_PROMPT = """A patient is asking for help choosing between doctors for their dental condition.

Specialties needed: {specialties}
Patient symptoms: {symptoms}

Provide practical guidance (2-3 sentences) on how to prioritize which specialty to address FIRST.

Rules:
- If symptoms include pain/sensitivity → prioritize Endodontics first
- If impacted tooth → prioritize Oral Surgery first  
- If cosmetic/aligners only → Orthodontics can wait
- Suggest they pick based on URGENCY and AVAILABILITY

DO NOT recommend a specific doctor by name.
Keep it concise and actionable."""

def provide_doctor_selection_guidance(specialties: List[str], symptoms: List[str], doctors: List[Dict]) -> str:
    """Deterministic guidance with progressive detail."""
    
    relevant_doctors = [d for d in doctors if d["specialty"] in specialties]
    
    if not relevant_doctors:
        return "Please select from the doctors listed above."
    
    # Priority logic
    priority_specialty = None
    if any(s in " ".join(symptoms).lower() for s in ["pain", "sensitivity", "night", "abscess", "cracked"]):
        priority_specialty = "Endodontics"
    elif any(s in " ".join(symptoms).lower() for s in ["impacted", "wisdom", "extraction"]):
        priority_specialty = "Oral Surgery"
    
    if priority_specialty and priority_specialty in specialties:
        priority_docs = [d for d in relevant_doctors if d["specialty"] == priority_specialty]
        
        if len(priority_docs) == 2:
            # User keeps asking — give more detail
            return (
                f"💡 Both Dr. {priority_docs[0]['name'].split()[-1]} and Dr. {priority_docs[1]['name'].split()[-1]} "
                f"are qualified endodontists.\n\n"
                f"**Choosing criteria:**\n"
                f"- **Schedule:** Dr. {priority_docs[0]['name'].split()[-1]} has {priority_docs[0]['clinic']} slots\n"
                f"- **Convenience:** Pick based on which day/time works best for you\n\n"
                f"I cannot recommend one over the other based on qualifications — both are equally skilled. "
                f"Your choice should be based on availability.\n\n"
                f"Please select: 'Dr. [Name], [Day] [Time]'"
            )
        
        elif len(priority_docs) == 1:
            return (
                f"💡 **{priority_docs[0]['name']}** is the available {priority_specialty} specialist.\n\n"
                f"Reply with: 'Dr. {priority_docs[0]['name'].split()[-1]}, [your preferred slot]'"
            )
    
    # Fallback
    return (
        f"All doctors are equally qualified. Choose based on:\n"
        f"1. Which specialty you want to address first\n"
        f"2. Which day/time fits your schedule\n\n"
        f"Reply: 'Dr. [Name], [Day] [Time]'"
    )


# ─────────────────────────────────────────────
# MODULE 11: Doctor & Slot Extractor (Pure LLM)
# ─────────────────────────────────────────────

EXTRACT_DOCTOR_SLOT_PROMPT = """Extract the doctor and slot from this booking message.

User message: "{message}"

Available doctors:
{doctors}
Rules:
- Match partial names (e.g., "Sneha" matches "Dr. Sneha Kapoor").
- If user mentions a day like "Wed", match it to "Wednesday".
- Return ONLY JSON.

User's time preference: {time_pref}

Return ONLY a JSON object:
{{
  "doctor_found": bool,
  "doctor_name": "full name from the list",
  "slot_found": bool,
  "slot_day": "full day name",
  "slot_time": "time"
}}
Be flexible with variations (Dr. Mehta, Mehta, mehta, Wed, Wednesday, 9am, etc.)"""

def extract_doctor_and_slot(message: str, doctors: List[Dict], time_pref: str) -> Dict:
    doctor_list = "\n".join([f"- {d['name']} ({d['specialty']})" for d in doctors])
    prompt = EXTRACT_DOCTOR_SLOT_PROMPT.format(
        message=message,
        doctors=doctor_list,
        time_pref=time_pref
    )
    messages = [{"role": "user", "content": prompt}]
    result = _chat(messages, temperature=0.1)
    
    import json
    try:
        data = json.loads(result.strip().strip("`").replace("```json", "").replace("```", ""))
        
        # Match doctor
        if data.get("doctor_found"):
            doctor_name = data.get("doctor_name", "")
            matched_doctor = None
            for d in doctors:
                if doctor_name.lower() in d["name"].lower() or d["name"].lower() in doctor_name.lower():
                    matched_doctor = d
                    break
            data["doctor"] = matched_doctor
            
            # Match slot
            if matched_doctor and data.get("slot_found"):
                from app.scheduler import get_available_slots
                slots = get_available_slots(matched_doctor["id"])
                slot_day = data.get("slot_day", "")
                slot_time = data.get("slot_time", "")
                
                for s in slots:
                    day_match = slot_day.lower() in s["day"].lower()
                    time_match = slot_time.replace(":", "").replace(" ", "").lower() in s["time"].replace(":", "").replace(" ", "").lower()
                    if day_match and time_match:
                        data["slot"] = s
                        break
        
        return data
    except:
        return {"doctor_found": False}


# ─────────────────────────────────────────────
# MODULE 12: Insurance Validator (LLM)
# ─────────────────────────────────────────────

INSURANCE_VALIDATE_PROMPT = """Analyze this insurance input.

User message: "{message}"
Input type: {input_type}

Return ONLY a JSON object:
{{
  "skip_insurance": bool ((True if user says no, none, don't have, skip, self-pay, etc.),
  "provider": "provider name if found",
  "policy_id": "policy ID if found",
  "valid_policy_id": bool (5-20 chars, alphanumeric, has digits)
}}
Example 1: "no insurance" -> {{"skip_insurance": true, "provider": null}}
Example 2: "I have Delta Dental" -> {{"skip_insurance": false, "provider": "Delta Dental"}}
Handle filler phrases like "yes I have Delta Dental" → extract "Delta Dental"."""

def validate_insurance_input(message: str, input_type: str) -> Dict:
    prompt = INSURANCE_VALIDATE_PROMPT.format(message=message, input_type=input_type)
    messages = [{"role": "user", "content": prompt}]
    result = _chat(messages, temperature=0.1)
    
    import json
    try:
        return json.loads(result.strip().strip("`").replace("```json", "").replace("```", ""))
    except:
        return {}
    
# ─────────────────────────────────────────────
# MODULE 13: Clinical Term Explainer
# ─────────────────────────────────────────────

def explain_clinical_term(user_question: str, our_question: str) -> str:
    """Explain clinical terminology in simple language."""
    prompt = f"""The patient asked: "{user_question}"

This was in response to our question: "{our_question}"

Provide a simple, 1-2 sentence explanation of the clinical term they're asking about.
Then re-ask the original question in simpler language.

Keep it conversational and helpful."""

    messages = [{"role": "user", "content": prompt}]
    return _chat(messages, temperature=0.3)


# ─────────────────────────────────────────────
# MODULE 14: Relative Time Parser
# ─────────────────────────────────────────────

def parse_relative_time(time_phrase: str) -> str:
    """Convert 'tomorrow', 'today', 'next week' to actual day names."""
    from datetime import datetime, timedelta
    
    phrase_lower = time_phrase.lower().strip()
    today = datetime.now()
    
    # Relative mappings
    if "tomorrow" in phrase_lower:
        tomorrow = today + timedelta(days=1)
        return tomorrow.strftime("%A")  # Returns day name like "Tuesday"
    
    if "today" in phrase_lower:
        return today.strftime("%A")
    
    if "next week" in phrase_lower:
        next_week = today + timedelta(days=7)
        return f"next {next_week.strftime('%A')}"
    
    # If contains day name, return as-is
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for day in days:
        if day in phrase_lower:
            return day.capitalize()
    
    return time_phrase