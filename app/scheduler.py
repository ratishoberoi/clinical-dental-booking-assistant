import json
import os
from typing import List, Optional, Dict

# Load DB once at startup
BASE_DIR = os.path.dirname(__file__)
DOCTORS_PATH = os.path.join(BASE_DIR, "data", "doctors.json")
SLOTS_PATH = os.path.join(BASE_DIR, "data", "slots.json")

with open(DOCTORS_PATH) as f:
    DOCTORS_DB = json.load(f)["doctors"]

with open(SLOTS_PATH) as f:
    SLOTS_DB = json.load(f)["slots"]


# ─── Time Preference Matching ──────────────────────

TIME_KEYWORDS = {
    "morning": ["8:00 AM", "9:00 AM", "9:30 AM", "10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM"],
    "afternoon": ["12:00 PM", "1:00 PM", "2:00 PM", "3:00 PM", "3:30 PM", "4:00 PM"],
    "evening": ["5:00 PM", "5:30 PM", "6:00 PM", "6:30 PM", "7:00 PM"],
    "weekend": ["Saturday", "Sunday"],
    "weekday": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
    "saturday": ["Saturday"],
    "sunday": ["Sunday"],
    "monday": ["Monday"],
    "tuesday": ["Tuesday"],
    "wednesday": ["Wednesday"],
    "thursday": ["Thursday"],
    "friday": ["Friday"],
}

DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def get_all_days_in_db() -> set:
    """Return only days that actually exist in the slots DB. No hallucination."""
    return {slot["day"] for slot in SLOTS_DB if not slot["booked"]}


def parse_time_preference(preference_text: str) -> Dict:
    """Extract day and time preferences from natural language.
    Guards against claiming availability for days not present in DB."""
    text = preference_text.lower()
    preferred_days = []
    preferred_times = []

    actual_days_in_db = get_all_days_in_db()

    for keyword, values in TIME_KEYWORDS.items():
        if keyword in text:
            if keyword in DAY_NAMES or keyword in ["weekend", "weekday"]:
                # GUARD: Only include days that actually have slots in DB
                valid_days = [v for v in values if v in actual_days_in_db]
                preferred_days.extend(valid_days)
            else:
                preferred_times.extend(values)

    return {
        "preferred_days": list(set(preferred_days)),
        "preferred_times": list(set(preferred_times)),
        "raw": preference_text,
        "actual_days_available": sorted(actual_days_in_db)  # transparency for debugging
    }


def get_doctors_by_specialty(specialty: str) -> List[Dict]:
    """Return all doctors for a given specialty."""
    return [d for d in DOCTORS_DB if d["specialty"] == specialty]


def get_available_slots(doctor_id: str) -> List[Dict]:
    """Return unbooked slots for a doctor."""
    return [s for s in SLOTS_DB if s["doctor_id"] == doctor_id and not s["booked"]]


def filter_slots_by_preference(slots: List[Dict], preference: Dict) -> List[Dict]:
    """Filter slots based on parsed time preference."""
    preferred_days = preference.get("preferred_days", [])
    preferred_times = preference.get("preferred_times", [])

    if not preferred_days and not preferred_times:
        return slots[:3]  # Return first 3 if no preference

    matched = []
    for slot in slots:
        day_match = not preferred_days or slot["day"] in preferred_days
        time_match = not preferred_times or slot["time"] in preferred_times
        if day_match and time_match:
            matched.append(slot)

    # If no exact match, relax constraint (day-only or time-only)
    if not matched and preferred_days:
        matched = [s for s in slots if s["day"] in preferred_days]

    # If still no match — show actual available slots, clearly labeled
    # Do NOT show random slots silently as if they matched preference
    return matched[:4] if matched else []


def build_doctor_slot_display(specialties: List[str], time_preference: str) -> str:
    """Build the formatted doctor + slot display string.
    Only shows slots that genuinely exist in DB — no hallucinated availability."""
    preference = parse_time_preference(time_preference)
    output_lines = []

    # Show user what days are actually available if their preferred days had no match
    actual_days = preference.get("actual_days_available", [])

    for specialty in specialties:
        doctors = get_doctors_by_specialty(specialty)
        if not doctors:
            continue

        output_lines.append(f"**{specialty}**")
        output_lines.append("")

        for doctor in doctors:
            all_slots = get_available_slots(doctor["id"])

            # No slots at all for this doctor — skip silently
            if not all_slots:
                continue

            filtered_slots = filter_slots_by_preference(all_slots, preference)
            output_lines.append(f"🩺 **{doctor['name']}** — {doctor['clinic']}")

            if filtered_slots:
                slot_strs = [f"{s['day']} {s['time']}" for s in filtered_slots]
                output_lines.append(f"   ✓ Matching slots: {' | '.join(slot_strs)}")
            else:
                fallback = all_slots[:2]
                if fallback:
                    slot_strs = [f"{s['day']} {s['time']}" for s in fallback]
                    output_lines.append(f"   ⚠️ No match for your preference — next available: {' | '.join(slot_strs)}")


            output_lines.append("")

        output_lines.append("---")

    # If preferred days had zero DB coverage, tell the user honestly
    if preference["preferred_days"] == [] and time_preference.strip():
        days_note = ", ".join(actual_days) if actual_days else "None currently"
        output_lines.append(f"📅 *Note: Days with actual availability: {days_note}*")

    return "\n".join(output_lines)

def get_doctor_slots_for_confirmation(doctor_id: str, time_preference: str) -> List[Dict]:
    """Get filtered slots for a specific doctor after selection."""
    preference = parse_time_preference(time_preference)
    slots = get_available_slots(doctor_id)
    return filter_slots_by_preference(slots, preference)


def confirm_booking(slot_id: str) -> bool:
    """Mark a slot as booked."""
    for slot in SLOTS_DB:
        if slot["slot_id"] == slot_id:
            slot["booked"] = True
            return True
    return False


def get_doctor_by_id(doctor_id: str) -> Optional[Dict]:
    return next((d for d in DOCTORS_DB if d["id"] == doctor_id), None)


def get_slot_by_id(slot_id: str) -> Optional[Dict]:
    return next((s for s in SLOTS_DB if s["slot_id"] == slot_id), None)


def find_doctor_by_name(name_fragment: str) -> Optional[Dict]:
    """Find doctor by partial name match — handles Dr.Mehta, Mehta, mehta, DR MEHTA etc."""
    # Normalize input
    name_lower = name_fragment.lower()
    name_lower = name_lower.replace(".", " ").replace(",", " ").replace("-", " ")
    name_lower = " ".join(name_lower.split())  # collapse multiple spaces
    input_words = [w for w in name_lower.split() if w not in ["dr", "doctor", "the"]]

    for doctor in DOCTORS_DB:
        doctor_name_lower = doctor["name"].lower().replace(".", " ").replace(",", " ")
        doctor_words = doctor_name_lower.split()

        for word in input_words:
            if len(word) >= 3:
                for dw in doctor_words:
                    if word == dw or word in dw or dw in word:
                        return doctor

        # Final fallback — cleaned input substring in doctor name
        cleaned_input = "".join(input_words)
        cleaned_doctor = "".join(doctor_words)
        if cleaned_input in cleaned_doctor:
            return doctor

    return None


def find_slot_by_day_time(doctor_id: str, day_or_time: str) -> Optional[Dict]:
    """Find slot by flexible day/time — handles Wed, wednesday, 9am, 9:00, saturday etc."""
    text = day_or_time.lower().replace(".", "").replace(",", "").strip()
    slots = get_available_slots(doctor_id)

    DAY_ALIASES = {
        "mon": "monday", "tue": "tuesday", "tues": "tuesday",
        "wed": "wednesday", "weds": "wednesday", "thu": "thursday",
        "thur": "thursday", "thurs": "thursday", "fri": "friday",
        "sat": "saturday", "sun": "sunday"
    }

    # Normalize day aliases in input
    for alias, full in DAY_ALIASES.items():
        if alias in text:
            text = text.replace(alias, full)

    # Normalize time formats — "9am" -> "9:00 am", "930" -> "9:30"
    import re
    text = re.sub(r'(\d+)\s*am', r'\1:00 am', text)
    text = re.sub(r'(\d+)\s*pm', r'\1:00 pm', text)
    text = re.sub(r'(\d+):(\d+)\s*am', r'\1:\2 am', text)
    text = re.sub(r'(\d+):(\d+)\s*pm', r'\1:\2 pm', text)

    for slot in slots:
        slot_day = slot["day"].lower()
        slot_time = slot["time"].lower()
        if slot_day in text or slot_time in text:
            return slot

    return None