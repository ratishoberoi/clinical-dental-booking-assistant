from typing import Optional, Tuple


KNOWN_PROVIDERS = [
    "United HealthCare", "Delta Dental", "Cigna", "Aetna", "MetLife",
    "Guardian", "Humana", "Sun Life", "Principal", "Anthem",
    "Blue Cross", "Blue Shield", "BCBS"
]


def looks_like_provider(text: str) -> bool:
    """Heuristic: does this text look like an insurance provider name?"""
    text_lower = text.lower().strip()

    # Strip filler phrases users add
    FILLER = ["yes", "i have", "my insurance is", "insurance is",
              "it's", "its", "provider is", "i use", "with"]
    for f in FILLER:
        text_lower = text_lower.replace(f, "").strip()

    # Check known providers after stripping fillers
    for provider in KNOWN_PROVIDERS:
        if provider.lower() in text_lower:
            return True

    # Heuristic: 1-4 words, no digits
    words = text_lower.strip().split()
    has_digits = any(char.isdigit() for char in text_lower)
    if 1 <= len(words) <= 4 and not has_digits:
        return True

    return False


def looks_like_policy_id(text: str) -> bool:
    """
    Validate insurance policy/member ID format.
    Real IDs: alphanumeric, 6-20 chars, must have digits, often has dashes.
    Reject: pure random lowercase strings with no digits.
    """
    import re
    text = text.strip()

    # Must be 5-20 characters
    if not (5 <= len(text) <= 20):
        return False

    # Must contain at least one digit
    if not any(c.isdigit() for c in text):
        return False

    # Must be alphanumeric (with optional dashes/dots)
    if not re.match(r'^[A-Za-z0-9\-\.]+$', text):
        return False

    # Reject pure dictionary words (real IDs don't look like normal words)
    alpha_only = re.sub(r'[^a-zA-Z]', '', text).lower()
    COMMON_WORDS = ["yes", "no", "none", "delta", "cigna", "aetna", "insurance",
                    "policy", "member", "number", "random", "string", "test"]
    if alpha_only in COMMON_WORDS:
        return False

    return True


def parse_insurance_from_message(message: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Try to extract both provider and policy ID from a single message.
    Returns (provider, policy_id) — either can be None.
    """
    provider = None
    policy_id = None

    # Check if message contains both on separate lines or with keywords
    message_lower = message.lower()

    lines = message.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if any(kw in line.lower() for kw in ["provider", "insurance", "company", "carrier"]):
            # Extract value after colon if present
            if ":" in line:
                provider = line.split(":", 1)[1].strip()
            else:
                provider = line
        elif any(kw in line.lower() for kw in ["policy", "member id", "id", "number"]):
            if ":" in line:
                policy_id = line.split(":", 1)[1].strip()
            else:
                policy_id = line

    # Fallback: single message heuristic
    if not provider and not policy_id:
        if looks_like_provider(message):
            provider = message.strip()
        elif looks_like_policy_id(message):
            policy_id = message.strip()

    return provider, policy_id


def format_insurance_summary(provider: str, policy_id: str) -> str:
    return (
        f"✅ **Insurance Captured**\n"
        f"- Provider: {provider}\n"
        f"- Member/Policy ID: {policy_id}"
    )