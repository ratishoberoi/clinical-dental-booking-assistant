from typing import List
from app.llm_engine import route_to_specialties, classify_urgency

# Fallback keyword map — used only if LLM fails
FALLBACK_MAP = {
    "night pain": "Endodontics",
    "cold sensitivity": "Endodontics",
    "hot sensitivity": "Endodontics",
    "root canal": "Endodontics",
    "abscess": "Endodontics",
    "wisdom tooth": "Oral Surgery",
    "impacted": "Oral Surgery",
    "extraction": "Oral Surgery",
    "aligner": "Orthodontics",
    "invisalign": "Orthodontics",
    "braces": "Orthodontics",
    "gum bleeding": "Periodontics",
    "gum swelling": "Periodontics",
    "crown": "Restorative Dentistry",
    "filling": "Restorative Dentistry",
    "broken tooth": "Restorative Dentistry",
}

VALID_SPECIALTIES = [
    "Endodontics",
    "Oral Surgery",
    "Orthodontics",
    "Periodontics",
    "Restorative Dentistry",
]


def get_specialties(collected_symptoms: List[str]) -> List[str]:
    """Primary: LLM-driven routing. Fallback: keyword map."""
    try:
        specialties = route_to_specialties(collected_symptoms)
        # Validate returned specialties are real ones
        valid = [s for s in specialties if s in VALID_SPECIALTIES]
        if valid:
            return valid
    except Exception:
        pass

    # Fallback keyword matching
    symptom_text = " ".join(collected_symptoms).lower()
    matched = []
    for keyword, specialty in FALLBACK_MAP.items():
        if keyword in symptom_text and specialty not in matched:
            matched.append(specialty)
    return matched if matched else ["Restorative Dentistry"]


def get_urgency(collected_symptoms: List[str]) -> str:
    """Classify urgency level of patient's condition."""
    try:
        return classify_urgency(collected_symptoms)
    except Exception:
        return "URGENT"


def get_urgency_prefix(urgency: str) -> str:
    """Returns a clinical urgency note to prepend to responses."""
    if urgency == "EMERGENCY":
        return "⚠️ **Clinical Note:** Your symptoms indicate a possible dental emergency. Please seek immediate care.\n\n"
    elif urgency == "URGENT":
        return "🔶 **Clinical Note:** Your symptoms suggest an urgent condition that should be evaluated soon.\n\n"
    return ""