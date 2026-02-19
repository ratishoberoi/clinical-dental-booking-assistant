import os
from openai import OpenAI
from groq import Groq
from typing import List, Optional
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