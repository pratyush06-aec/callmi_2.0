# (callmi)Outbound Sales AI Agent

An advanced, real-time outbound sales AI agent (a web development and e-commerce agency). Powered by LiveKit Agents, Groq openai/gpt-oss-20b, Sarvam AI Bulbul v4 Flash TTS, and Deepgram STT, this system automatically dials leads, qualifies them, seamlessly switches languages (English, Hindi, Telugu), and sends intelligent WhatsApp follow-ups pre-call, mid-call, and post-call, based on hot/warm/cold leads, containing the summary of the context about the conversation over call.

## 🚀 Key Features

*   **Ultra-Low Latency Voice Pipeline:** Uses Deepgram Nova-3 for real-time Speech-to-Text, Groq's fast openai/gpt-oss-20b model for intelligent dialogue and tool usage, and Sarvam AI Bulbul v4 Flash for low-latency Indian multilingual Text-to-Speech.
*   **Proactive Outbound SIP Calling:** Fully capable of dialing real-world phone numbers using a SIP Trunk (e.g., Twilio) via the LiveKit API (`trigger.py`), bypassing local TRAI restrictions by routing through an international number.
*   **Multilingual Code-Switching:** Naturally converses and dynamically code-switches between English, Hindi, and Telugu depending entirely on the user's spoken language.
*   **Dynamic Intent Classification & Actions:** The AI autonomously classifies leads into Hot, Warm, or Cold based on their budget, timeline, and requirements.
*   **Green API WhatsApp Integrations (Pre-Call, Mid-Call & Post-Call):**
    *   **Pre-Call Context:** Sends a WhatsApp message from your actual personal number via Green API immediately before the SIP call rings, giving the callee context so they don't ignore the international SIP caller ID.
    *   **Mid-Call Portfolio:** Hot leads instantly receive a mid-call WhatsApp message with an exclusive portfolio link without disconnecting the ongoing voice call.
    *   **Post-Call Summaries:** All leads automatically receive a post-call WhatsApp message containing a detailed summary of their requirements, a resume link, a GitHub repo link, a system architecture diagram link, and any dynamically scheduled callback times.
*   **Automated Callback Scheduling:** If a lead is busy or prefers to talk later, the agent saves the spoken requested time directly into the local database and includes it in the WhatsApp summary.
*   **Strict Domain Guardrails:** Enforced system prompt boundaries ensure the agent strictly refuses to discuss topics outside of web development and e-commerce.

---

## 🏗️ System Architecture

📄 **[View Full System Architecture & Workflow Diagram](https://drive.google.com/file/d/1WDBfwrhDuI7mN2cMAd-80kGymC1N44fS/view)**

The project consists of a purely Python-based backend that handles SIP communication, LLM inference, and external API requests:

*   **`src/agent.py`**: The core LiveKit agent entrypoint. Contains the LLM system prompt, tool definitions (discovery, classification, scheduling), and WebRTC event hooks (like triggering the mid-call and post-call WhatsApp summaries).
*   **`src/db.py`**: A lightweight SQLite wrapper for securely storing lead data, saving callback times, and persisting discovery details locally.
*   **`trigger.py`**: The CLI script responsible for dispatching the agent, sending the pre-call WhatsApp ping via Green API, and initiating the outbound SIP call.
*   **LiveKit Cloud**: Handles the WebRTC media streaming, VAD (Voice Activity Detection using Silero), and SIP Trunking.
*   **Green API**: Provides unofficial WhatsApp API integration to send messages from a personal mobile number.

---

## 🛠️ Required API Dependencies & Credentials

This project heavily relies on cloud services. You will need to create a `.env.local` file inside the `backend/` directory with your own API keys. 

**Backend (`backend/.env.local`):**
```env
# -----------------------------------------------------------------------------
# LiveKit (real-time transport)
# Get these from https://cloud.livekit.io/ → your project → Settings
# -----------------------------------------------------------------------------
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key_here
LIVEKIT_API_SECRET=your_livekit_api_secret_here

# -----------------------------------------------------------------------------
# Deepgram (STT — Speech-to-Text)
# Get your API key from https://deepgram.com
# -----------------------------------------------------------------------------
DEEPGRAM_API_KEY=your_deepgram_api_key_here

# -----------------------------------------------------------------------------
# LLM — use one of the following depending on which provider you use
# -----------------------------------------------------------------------------
# For Groq: get from https://console.groq.com/keys
GROQ_API_KEY=your_groq_api_key_here

# -----------------------------------------------------------------------------
# Sarvam AI (TTS — Bulbul v4 Flash)
# -----------------------------------------------------------------------------
SARVAM_API_KEY=your_sarvam_api_key_here

# -----------------------------------------------------------------------------
# Telephony
# -----------------------------------------------------------------------------
SIP_OUTBOUND_TRUNK_ID=your_sip_outbound_trunk_id_here

# -----------------------------------------------------------------------------
# Green API (WhatsApp API)
# -----------------------------------------------------------------------------
GREEN_API_ID_INSTANCE=your_id_instance_here
GREEN_API_API_TOKEN_INSTANCE=your_api_token_instance_here
```

---

## 📦 Python Dependencies

Managed via `uv` in `backend/pyproject.toml`:
*   `livekit-agents` (Core framework)
*   `livekit-api` (For triggering SIP calls)
*   `livekit-plugins-groq` (LLM integration)
*   `livekit-plugins-sarvam` (TTS integration with Bulbul v4 Flash)
*   `livekit-plugins-noise-cancellation` (Audio cleanup)
*   `aiohttp` & `urllib` (For REST API requests)
*   `python-dotenv` (Environment management)
*   `pytest` (For testing)

---

## 🚀 Running the Agent

### 1. Install Dependencies
```bash
cd backend
uv sync
```

### 2. Start the Agent Worker
This will connect your local Python process to LiveKit Cloud and prepare it to receive agent dispatch requests.
```bash
uv run python src/agent.py dev
```

### 3. Trigger an Outbound Phone Call
In a separate terminal, use the trigger script to dial the target phone number.
```bash
cd backend
uv run python trigger.py
```
*The script will send a pre-call WhatsApp message to notify the target, then initiate the SIP call. The agent will wait for the target to pick up and then say its opening line.*
