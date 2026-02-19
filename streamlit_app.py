import streamlit as st
import requests
import uuid

API_BASE = "http://127.0.0.1:8000"

# ── Page Config ──
st.set_page_config(
    page_title="Dental Booking Assistant",
    page_icon="🦷",
    layout="centered"
)

# ── Custom CSS ──
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');
    
    * { font-family: 'Inter', sans-serif; }
    
    .main { background-color: #f8fafc; }
    
    .stApp {
        background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 50%, #f0fdf4 100%);
        min-height: 100vh;
    }
    
    /* Header */
    .header-box {
        background: linear-gradient(135deg, #0ea5e9, #0284c7);
        border-radius: 16px;
        padding: 24px 32px;
        margin-bottom: 24px;
        color: white;
        box-shadow: 0 4px 20px rgba(14, 165, 233, 0.3);
    }
    .header-box h1 { margin: 0; font-size: 1.6rem; font-weight: 600; }
    .header-box p { margin: 6px 0 0; opacity: 0.85; font-size: 0.9rem; }
    
    /* Stage badge */
    .stage-badge {
        display: inline-block;
        background: #dbeafe;
        color: #1d4ed8;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 500;
        margin-bottom: 16px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    /* Chat messages */
    .msg-user {
        background: #0ea5e9;
        color: white;
        padding: 12px 18px;
        border-radius: 18px 18px 4px 18px;
        margin: 8px 0 8px 20%;
        font-size: 0.92rem;
        line-height: 1.5;
        box-shadow: 0 2px 8px rgba(14,165,233,0.2);
    }
    
    .msg-assistant {
        background: white;
        color: #1e293b;
        padding: 14px 18px;
        border-radius: 18px 18px 18px 4px;
        margin: 8px 20% 8px 0;
        font-size: 0.92rem;
        line-height: 1.6;
        box-shadow: 0 2px 12px rgba(0,0,0,0.07);
        border-left: 3px solid #0ea5e9;
    }

    .msg-assistant-confirmed {
        background: #f0fdf4;
        color: #1e293b;
        padding: 14px 18px;
        border-radius: 18px 18px 18px 4px;
        margin: 8px 20% 8px 0;
        font-size: 0.92rem;
        line-height: 1.6;
        box-shadow: 0 2px 12px rgba(0,0,0,0.07);
        border-left: 3px solid #22c55e;
    }
    
    /* Input area */
    .stTextInput > div > div > input {
        border-radius: 12px !important;
        border: 2px solid #e2e8f0 !important;
        padding: 12px 16px !important;
        font-size: 0.95rem !important;
        transition: border-color 0.2s !important;
    }
    .stTextInput > div > div > input:focus {
        border-color: #0ea5e9 !important;
        box-shadow: 0 0 0 3px rgba(14,165,233,0.1) !important;
    }
    
    /* Buttons */
    .stButton > button {
        background: linear-gradient(135deg, #0ea5e9, #0284c7) !important;
        color: white !important;
        border: none !important;
        border-radius: 12px !important;
        padding: 10px 28px !important;
        font-weight: 500 !important;
        font-size: 0.95rem !important;
        transition: all 0.2s !important;
        box-shadow: 0 2px 8px rgba(14,165,233,0.3) !important;
    }
    .stButton > button:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 16px rgba(14,165,233,0.4) !important;
    }

    /* Sidebar */
    .sidebar-info {
        background: white;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        font-size: 0.85rem;
    }
    .sidebar-info h4 {
        margin: 0 0 10px;
        color: #0284c7;
        font-size: 0.9rem;
    }
    .sidebar-label {
        color: #64748b;
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 2px;
    }
    .sidebar-value {
        color: #1e293b;
        font-weight: 500;
        margin-bottom: 8px;
        font-size: 0.88rem;
    }

    /* Booking confirmed banner */
    .confirmed-banner {
        background: linear-gradient(135deg, #22c55e, #16a34a);
        color: white;
        padding: 16px 24px;
        border-radius: 12px;
        text-align: center;
        font-weight: 600;
        font-size: 1.1rem;
        margin-bottom: 16px;
        box-shadow: 0 4px 16px rgba(34,197,94,0.3);
    }

    /* Divider */
    hr { border-color: #e2e8f0; margin: 16px 0; }

    /* Hide streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Fix spinner color */
    .stSpinner > div {
        border-top-color: #0ea5e9 !important;
    }

    /* Clear input after send */
    .stTextInput > div > div > input {
        background: white !important;
        color: #1e293b !important;
        caret-color: #0ea5e9 !important;
    }
</style>
""", unsafe_allow_html=True)


# ── Session Init ──
def init_session():
    if "session_id" not in st.session_state:
        try:
            resp = requests.post(f"{API_BASE}/session/new")
            st.session_state.session_id = resp.json()["session_id"]
        except:
            st.session_state.session_id = str(uuid.uuid4())
    
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    if "current_stage" not in st.session_state:
        st.session_state.current_stage = "intake"
    
    if "booking_complete" not in st.session_state:
        st.session_state.booking_complete = False

    if "session_info" not in st.session_state:
        st.session_state.session_info = {}


def get_session_info():
    try:
        resp = requests.get(f"{API_BASE}/session/{st.session_state.session_id}")
        if resp.status_code == 200:
            st.session_state.session_info = resp.json()
    except:
        pass


def send_message(user_input: str):
    try:
        resp = requests.post(
            f"{API_BASE}/chat",
            json={
                "session_id": st.session_state.session_id,
                "user_message": user_input
            },
            timeout=120  # DeepSeek can be slow
        )
        if resp.status_code == 200:
            data = resp.json()
            st.session_state.messages.append({
                "role": "assistant",
                "content": data["assistant_message"]
            })
            st.session_state.current_stage = data["current_stage"]
            st.session_state.booking_complete = data["booking_complete"]
            get_session_info()
        else:
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"⚠️ Error: {resp.json().get('detail', 'Unknown error')}"
            })
    except requests.exceptions.Timeout:
        st.session_state.messages.append({
            "role": "assistant",
            "content": "⏳ Request timed out — the AI is thinking. Please try again."
        })
    except Exception as e:
        st.session_state.messages.append({
            "role": "assistant",
            "content": f"⚠️ Connection error: {str(e)}"
        })


def reset_conversation():
    try:
        requests.delete(f"{API_BASE}/session/{st.session_state.session_id}/reset")
    except:
        pass
    for key in ["session_id", "messages", "current_stage", "booking_complete", "session_info"]:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()


# ── Stage Display Names ──
STAGE_LABELS = {
    "intake": "🩺 Clinical Intake",
    "treatment_routing": "🔀 Specialty Routing",
    "time_preference": "📅 Time Preference",
    "doctor_slot_display": "👨‍⚕️ Doctor Selection",
    "doctor_selection": "👨‍⚕️ Doctor Selection",
    "insurance_provider": "🛡️ Insurance — Provider",
    "insurance_policy_id": "🛡️ Insurance — Policy ID",
    "slot_confirmation": "✅ Confirm Booking",
    "booking_confirmed": "🎉 Booking Confirmed",
}


# ── MAIN APP ──
init_session()

# Header
st.markdown("""
<div class="header-box">
    <h1>🦷 Dental Booking Assistant</h1>
    <p>AI-powered clinical triage and appointment scheduling</p>
</div>
""", unsafe_allow_html=True)

# Booking confirmed banner
if st.session_state.booking_complete:
    st.markdown('<div class="confirmed-banner">🎉 Appointment Successfully Booked!</div>', 
                unsafe_allow_html=True)

# Stage badge
stage_label = STAGE_LABELS.get(st.session_state.current_stage, st.session_state.current_stage)
st.markdown(f'<div class="stage-badge">Stage: {stage_label}</div>', unsafe_allow_html=True)

# ── Sidebar ──
with st.sidebar:
    st.markdown("### 🦷 Session Info")
    
    info = st.session_state.session_info
    
    # Stage
    st.markdown('<div class="sidebar-info">', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">Current Stage</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sidebar-value">{stage_label}</div>', unsafe_allow_html=True)
    
    # Symptoms
    symptoms = info.get("collected_symptoms", [])
    if symptoms:
        st.markdown('<div class="sidebar-label">Detected Symptoms</div>', unsafe_allow_html=True)
        for s in symptoms:
            st.markdown(f'<div class="sidebar-value">• {s}</div>', unsafe_allow_html=True)
    
    # Specialties
    specialties = info.get("routed_specialties", [])
    if specialties:
        st.markdown('<div class="sidebar-label">Routed Specialties</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="sidebar-value">{", ".join(specialties)}</div>', 
                    unsafe_allow_html=True)
    
    # Booking info
    booking = info.get("booking", {})
    if booking.get("doctor_name"):
        st.markdown('<div class="sidebar-label">Selected Doctor</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="sidebar-value">{booking["doctor_name"]}</div>', 
                    unsafe_allow_html=True)
    
    if booking.get("slot_day"):
        st.markdown('<div class="sidebar-label">Appointment Slot</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="sidebar-value">{booking["slot_day"]} at {booking["slot_time"]}</div>', 
                    unsafe_allow_html=True)
    
    insurance = booking.get("insurance", {})
    if insurance.get("provider"):
        st.markdown('<div class="sidebar-label">Insurance</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="sidebar-value">{insurance["provider"]}</div>', 
                    unsafe_allow_html=True)
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Session ID (debug)
    with st.expander("🔧 Debug Info"):
        st.code(st.session_state.session_id, language=None)
        st.write(f"Turns: {info.get('conversation_turns', 0)}")
        st.write(f"Intake Qs: {info.get('intake_questions_asked', 0)}")
    
    st.markdown("---")
    
    if st.button("🔄 Start New Conversation", use_container_width=True):
        reset_conversation()


# ── Welcome Message ──
if not st.session_state.messages:
    welcome = (
        "Hello! I'm your dental care assistant. I'll help you understand your symptoms "
        "and schedule an appointment with the right specialist.\n\n"
        "Please describe your dental concern — what's bothering you?"
    )
    st.session_state.messages.append({
        "role": "assistant",
        "content": welcome
    })

# ── Chat History ──
chat_container = st.container()
with chat_container:
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(f'<div class="msg-user">{msg["content"]}</div>', 
                       unsafe_allow_html=True)
        else:
            css_class = "msg-assistant-confirmed" if st.session_state.booking_complete and msg == st.session_state.messages[-1] else "msg-assistant"
            st.markdown(f'<div class="{css_class}">{msg["content"]}</div>', 
                       unsafe_allow_html=True)

# ── Input ──
st.markdown("---")

if not st.session_state.booking_complete:
    col1, col2 = st.columns([5, 1])
    
    with col1:
        # Auto-clear input after send
        if "input_key" not in st.session_state:
            st.session_state.input_key = 0

        user_input = st.text_input(
            "Your message",
            placeholder="Describe your symptoms or respond to the assistant...",
            label_visibility="collapsed",
            key=f"user_input_{st.session_state.input_key}"
        )
    
    with col2:
        send_clicked = st.button("Send →", use_container_width=True)
    
    if send_clicked and user_input.strip():
        st.session_state.messages.append({
            "role": "user",
            "content": user_input
        })
        st.session_state.input_key += 1  # This clears the input
        with st.spinner(""):
            send_message(user_input)
        st.rerun()
else:
    st.success("✅ Your appointment is confirmed! Use the sidebar to start a new conversation.")