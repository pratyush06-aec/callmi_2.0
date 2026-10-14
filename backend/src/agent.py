import logging
import os
import sys
import traceback
import json
import random
import string
import aiohttp
from pathlib import Path

# Force utf-8 encoding for standard output to prevent LiveKit CLI rich console crashes on Windows
if sys.stdout and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    cli,
    room_io,
    tokenize,
    function_tool,
    RunContext,
)
from livekit.plugins import deepgram, groq, noise_cancellation, silero, sarvam
from livekit.plugins.turn_detector.multilingual import MultilingualModel

import db
db.init_db()

# ── DEBUG: Configure logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agent")
# logger.setLevel(logging.DEBUG)

# ── DEBUG: Env file loading ─────────────────────────────────────────────────
env_path = Path(__file__).resolve().parent.parent / ".env.local"
# logger.debug("[ENV] Looking for .env.local at: %s (exists=%s)", env_path, env_path.exists())
load_dotenv(env_path, override=True)

# ── DEBUG: Verify critical env vars ─────────────────────────────────────────
    # Check for required environment variables
    # required_envs = [
    #     "LIVEKIT_URL",
    #     "LIVEKIT_API_KEY",
    #     "LIVEKIT_API_SECRET",
    #     "DEEPGRAM_API_KEY",
    #     "GOOGLE_API_KEY",
    #     "SIP_OUTBOUND_TRUNK_ID"
    # ] val = os.environ.get(var)
#     if val:
#         masked = val[:6] + "..." if len(val) > 6 else val
#         logger.debug("[ENV] %s = %s", var, masked)
#     else:
#         logger.error("[ENV] %s is NOT SET — this will cause failures!", var)

# logger.debug("[ENV] Python version: %s", sys.version)
# logger.debug("[ENV] Working directory: %s", os.getcwd())

# Change this prompt to change what your voice agent does.
# See README.md for example prompts (customer support, language tutor, receptionist).
SYSTEM_PROMPT = """
IDENTITY: You are a confident, bilingual sales representative for a premium web development agency.
OBJECTIVES: 
1. Pitch our e-commerce website development services.
2. Ask discovery questions to qualify the lead (budget, types of products they sell, timeline, required features).
3. Classify their buying intent (Hot, Warm, Cold).
FIRST RESPONSE RULE:
- On the very first message, greet the caller warmly in ENGLISH ONLY, introduce yourself, and ask if they are looking to build a website.
- Keep the greeting short, conversational, and friendly. Do NOT use any other languages in your first message.
LANGUAGE & SCRIPT:
- You are fully bilingual in Hindi, Telugu, and English. 
- WAIT for the caller's first response, then mirror their language and code-switching exactly for the rest of the call.
- Do NOT automatically switch languages or output multiple languages on your own. If the user speaks purely in a single language, stick STRICTLY to that language. If they mix languages, naturally mix and match those same languages.
- Always write every language in its own native script (e.g., Hindi → Devanagari, Telugu → Telugu script, English → Latin). Do not romanize Hindi or Telugu.
GUARDRAILS: 
- DOMAIN STRICTNESS: You must STRICTLY stick to your own domain of web development and e-commerce. Do NOT discuss, entertain, or answer questions about anything outside of this domain. If the user tries to discuss unrelated topics, you must explicitly tell them that your primary and only purpose is to help them build a website, and firmly steer the conversation back to web development.
- Never promise specific pricing without confirming with a human manager. Provide broad estimates only if pushed.
- Be polite but persistent in getting discovery answers.
- NEVER tell the user how you have classified their intent. Never say the words "Hot", "Warm", or "Cold" to the user.
TOOL USAGE:
- When you learn their budget, timeline, and requested features, you MUST call the `save_discovery_details` tool.
- When you determine they have high intent (e.g. they have a high budget and want to start soon), you MUST call the `classify_and_act` tool with intent_level "Hot" and include a detailed `call_context` summary to send them a mid-call WhatsApp immediately!
- If the lead is Warm or Cold, explicitly ask if they would like to schedule a callback for later. If they agree or suggest a time, use the `schedule_callback` tool.
STYLE: Speak in short, engaging sentences. Keep your pace conversational and enthusiastic.
"""

OUTBOUND_PROMPT_ADDENDUM = """
OUTBOUND CALL RULES:
- You are making an OUTBOUND sales call. The person did NOT call you — you called THEM.
- In your very first message, you MUST say: "Hello! We noticed you might be interested in taking your business online. Are you looking to build an e-commerce website?"
- If the person says they are not interested, politely thank them and say you will end the call.
- Do not wait for them to speak first. Speak immediately when the call connects.
"""




class Assistant(Agent):
    def __init__(self, phone_number: str | None = None, is_outbound: bool = False, call_id: int | None = None) -> None:
        self._call_id = call_id
        self._phone_number = phone_number
        # Append phone number to prompt context if available
        prompt = SYSTEM_PROMPT
        if is_outbound:
            prompt += OUTBOUND_PROMPT_ADDENDUM
        if phone_number:
            prompt += f"\n\n[SYSTEM] The caller's phone number is {phone_number}."

        super().__init__(instructions=prompt)


    @function_tool
    async def save_discovery_details(self, context: RunContext, budget: str, products: str, timeline: str, features: str) -> str:
        """Use this tool to save or update discovery details about a lead.
        
        Args:
            budget: The lead's budget (e.g. '$1000', 'unknown').
            products: What products they sell.
            timeline: Their required timeline.
            features: Key features they requested (e.g. 'payment gateway', 'inventory').
        """
        phone_number = self._phone_number if hasattr(self, '_phone_number') and self._phone_number else "unknown"
        db.upsert_discovery_details(phone_number, budget, products, timeline, features)
        self.call_summary = f"building an e-commerce website for {products} with a budget of {budget}, looking to start {timeline}, including features like {features}"
        return "Discovery details saved successfully."

    @function_tool
    async def schedule_callback(self, context: RunContext, spoken_time: str, parsed_iso_time: str) -> str:
        """Use this tool when a lead asks you to call them back later.
        
        Args:
            spoken_time: The exact words they used (e.g., 'tomorrow morning', 'next week').
            parsed_iso_time: A best-effort ISO datetime estimation of when to call them.
        """
        phone_number = self._phone_number if hasattr(self, '_phone_number') and self._phone_number else "unknown"
        db.schedule_callback(phone_number, spoken_time, parsed_iso_time)
        self.scheduled_callback_time = spoken_time
        return "Callback scheduled successfully."

    @function_tool
    async def classify_and_act(self, context: RunContext, intent_level: str, barrier: str, call_context: str) -> str:
        """Use this tool to classify the lead's buying intent and trigger mid-call actions.
        Call this when you have enough discovery information or when the lead makes a firm decision.
        
        Args:
            intent_level: Must be exactly "Hot", "Warm", or "Cold".
            barrier: The main objection or barrier to closing (e.g., 'budget', 'timeline', 'None').
            call_context: A detailed summary of what the lead wants (budget, timeline, features).
        """
        phone_number = self._phone_number if hasattr(self, '_phone_number') and self._phone_number else "unknown"
        self.call_summary = call_context
        
        if intent_level == "Hot":
            # Send immediate WhatsApp message with context via Green API
            green_api_id = os.environ.get("GREEN_API_ID_INSTANCE")
            green_api_token = os.environ.get("GREEN_API_API_TOKEN_INSTANCE")
            green_api_host = os.environ.get("GREEN_API_HOST")
            
            if green_api_id and green_api_token and green_api_host and phone_number != "unknown":
                try:
                    url = f"https://{green_api_host}/waInstance{green_api_id}/sendMessage/{green_api_token}"
                    
                    # Format phone number for Green API (remove +, add @c.us)
                    target = phone_number.replace("+", "")
                    to_number = f"{target}@c.us"
                    
                    message_body = (
                        f"Hello! 🚀\n\n"
                        f"It is great speaking with you. Just to confirm while we are on the phone, here is a quick summary of what you are looking for:\n• {call_context}\n\n"
                        f"I will send over our architecture and my resume as soon as we wrap up the call!"
                    )
                    
                    payload = {
                        "chatId": to_number,
                        "message": message_body
                    }
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.post(url, json=payload) as response:
                            if response.status not in (200, 201):
                                logger.error("Failed to send WhatsApp: %s", await response.text())
                            else:
                                logger.info("Mid-call WhatsApp sent successfully via Green API!")
                except Exception as e:
                    logger.error("Error sending WhatsApp: %s", e)
            else:
                logger.warning("Missing Green API credentials or phone number. WhatsApp not sent.")
                
        return f"Lead classified as {intent_level}. Actions taken."




server = AgentServer()
# logger.debug("[SERVER] AgentServer created")


def prewarm(proc: JobProcess):
    # logger.debug("[PREWARM] Starting prewarm — loading Silero VAD model...")
    try:
        proc.userdata["vad"] = silero.VAD.load()
        # logger.debug("[PREWARM] Silero VAD model loaded successfully")
    except Exception as e:
        # logger.error("[PREWARM] Failed to load Silero VAD model: %s", e)
        # logger.error("[PREWARM] Traceback:\n%s", traceback.format_exc())
        raise


server.setup_fnc = prewarm
# logger.debug("[SERVER] Prewarm function registered")


def send_post_call_summary(phone_number: str, call_summary: str = "", scheduled_time: str = None):
    """Sends a post-call summary via Twilio WhatsApp with resume, diagram links, and callback times."""
    import os
    import logging
    import urllib.request
    import urllib.parse
    import base64
    import json

    logger = logging.getLogger("livekit.agents")
    if not phone_number or phone_number == "unknown":
        logger.warning("Cannot send post-call summary: unknown phone number.")
        return

    green_api_id = os.environ.get("GREEN_API_ID_INSTANCE")
    green_api_token = os.environ.get("GREEN_API_API_TOKEN_INSTANCE")
    green_api_host = os.environ.get("GREEN_API_HOST")
    fallback_phone = os.environ.get("FALLBACK_PHONE_NUMBER")
    resume_url = os.environ.get("RESUME_URL")

    if not (green_api_id and green_api_token and green_api_host):
        logger.warning("Green API credentials or host missing. Skipping post-call summary.")
        return

    try:
        target = phone_number.replace("+", "")
        to_number = f"{target}@c.us"
        
        context_str = f"Here is a quick summary of what you are looking for:\n• {call_summary}" if call_summary else "Here is a quick summary of your e-commerce website requirements:"
        schedule_str = f"We have also noted that you'd like us to call you back {scheduled_time}.\n\n" if scheduled_time else ""
        resume_str = f"📄 Resume: {resume_url}\n" if resume_url else ""
        contact_str = f"If you have any further questions or want to get started, you can reach me directly at my mobile number: {fallback_phone}.\n\n" if fallback_phone else ""
        
        message_body = (
            f"Hi there! Thank you for speaking with me today. 🚀\n\n"
            f"{context_str}\n\n"
            f"{schedule_str}"
            f"As promised, here is our architecture diagram and my resume for your review:\n"
            f"{resume_str}"
            f"{contact_str}"
            f"I look forward to taking your business online!"
        )

        url = f"https://{green_api_host}/waInstance{green_api_id}/sendMessage/{green_api_token}"
        
        payload = {
            "chatId": to_number,
            "message": message_body
        }
        
        data = json.dumps(payload).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        
        with urllib.request.urlopen(req) as resp:
            if resp.status in (200, 201):
                logger.info("Post-call WhatsApp summary sent successfully via Green API!")
            else:
                logger.error(f"Failed to send post-call WhatsApp: {resp.status}")
                
    except urllib.error.HTTPError as e:
        logger.error(f"Failed to send post-call WhatsApp: {e.code} - {e.read().decode('utf-8')}")
    except Exception as e:
        logger.error(f"Exception sending post-call WhatsApp: {e}")


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: JobContext):
    # logger.debug("═" * 60)
    # logger.debug("[SESSION] my_agent() called — new session starting")
    # logger.debug("[SESSION] Room name: %s", ctx.room.name)
    # logger.debug("[SESSION] Room SID: %s", ctx.room.sid)

    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # ── DEBUG: STT init ─────────────────────────────────────────────────
    # logger.debug("[STT] Initializing Deepgram STT (model=nova-3)...")
    try:
        stt = deepgram.STT(model="nova-3", language="multi")
        # logger.debug("[STT] Deepgram STT created successfully")
    except Exception as e:
        # logger.error("[STT] Failed to create Deepgram STT: %s", e)
        # logger.error("[STT] Traceback:\n%s", traceback.format_exc())
        raise

    # ── DEBUG: LLM init ─────────────────────────────────────────────────
    try:
        llm = groq.LLM(model="openai/gpt-oss-20b", temperature=0.5)
        # logger.debug("[LLM] Groq LLM created successfully")
    except Exception as e:
        # logger.error("[LLM] Failed to create Groq LLM: %s", e)
        # logger.error("[LLM] Traceback:\n%s", traceback.format_exc())
        raise
    # ── DEBUG: TTS init ─────────────────────────────────────────────────
    # logger.debug("[TTS] Initializing Sarvam Bulbul v4 flash TTS...")
    try:
        tts = sarvam.TTS(
            model="bulbul:v4-flash",
            api_key=os.environ.get("SARVAM_API_KEY"),
        )
        # logger.debug("[TTS] Sarvam TTS created successfully")
    except Exception as e:
        # logger.error("[TTS] Failed to create Sarvam TTS: %s", e)
        # logger.error("[TTS] Traceback:\n%s", traceback.format_exc())
        raise

    # ── DEBUG: Turn detector init ───────────────────────────────────────
    # logger.debug("[TURN] Initializing MultilingualModel turn detector...")
    try:
        turn_detection = MultilingualModel()
        # logger.debug("[TURN] Turn detector created successfully")
    except Exception as e:
        # logger.error("[TURN] Failed to create turn detector: %s", e)
        # logger.error("[TURN] Traceback:\n%s", traceback.format_exc())
        raise

    # ── DEBUG: VAD retrieval ────────────────────────────────────────────
    # logger.debug("[VAD] Retrieving prewarmed VAD from proc.userdata...")
    try:
        vad = ctx.proc.userdata["vad"]
        # logger.debug("[VAD] VAD retrieved successfully: %s", type(vad).__name__)
    except KeyError as e:
        # logger.error("[VAD] VAD not found in proc.userdata! Prewarm may have failed. Key: %s", e)
        raise

    # ── DEBUG: Pipeline setup ───────────────────────────────────────────
    # logger.debug("[PIPELINE] Setting up voice pipeline...")
    # Set up a voice AI pipeline using Sarvam AI (Bulbul v4 flash), Groq, Deepgram, and the LiveKit turn detector
    try:
        session = AgentSession(
            # Speech-to-text (STT) is your agent's ears, turning the user's speech into text that the LLM can understand
            # See all available models at https://docs.livekit.io/agents/models/stt/
            stt=stt,
            # A Large Language Model (LLM) is your agent's brain, processing user input and generating a response
            # See all available models at https://docs.livekit.io/agents/models/llm/
            llm=llm,
            # Text-to-speech (TTS) is your agent's voice, turning the LLM's text into speech that the user can hear
            # See all available models as well as voice selections at https://docs.livekit.io/agents/models/tts/
            tts=tts,
            # VAD and turn detection are used to determine when the user is speaking and when the agent should respond
            # See more at https://docs.livekit.io/agents/build/turns
            turn_detection=turn_detection,
            vad=vad,
            # allow the LLM to generate a response while waiting for the end of turn
            # See more at https://docs.livekit.io/agents/build/audio/#preemptive-generation
            preemptive_generation=True,
        )
        # logger.debug("[PIPELINE] AgentSession created successfully")
    except Exception as e:
        # logger.error("[PIPELINE] Failed to create AgentSession: %s", e)
        # logger.error("[PIPELINE] Traceback:\n%s", traceback.format_exc())
        raise

    # To use a realtime model instead of a voice pipeline, use the following session setup instead.
    # (Note: This is for the OpenAI Realtime API. For other providers, see https://docs.livekit.io/agents/models/realtime/))
    # 1. Install livekit-agents[openai]
    # 2. Set OPENAI_API_KEY in .env.local
    # 3. Add `from livekit.plugins import openai` to the top of this file
    # 4. Use the following session setup instead of the version above
    # session = AgentSession(
    #     llm=openai.realtime.RealtimeModel(voice="marin")
    # )

    # # Add a virtual avatar to the session, if desired
    # # For other providers, see https://docs.livekit.io/agents/models/avatar/
    # avatar = hedra.AvatarSession(
    #   avatar_id="...",  # See https://docs.livekit.io/agents/models/avatar/plugins/hedra
    # )
    # # Start the avatar and wait for it to join
    # await avatar.start(session, room=ctx.room)

    # ── DEBUG: Session start ────────────────────────────────────────────
    # logger.debug("[START] Starting session — connecting agent to room with noise cancellation...")
    try:
        # Extract phone number from participant identity if available
        remote_participant = next(iter(ctx.room.remote_participants.values()), None)
        phone_number = remote_participant.identity if remote_participant else None

        # Detect if this is an outbound call (room name starts with "outbound-")
        is_outbound = ctx.room.name.startswith("outbound-")
        
        # If it's an outbound call and participant hasn't fully joined yet, extract number from room name
        if is_outbound and not phone_number:
            parts = ctx.room.name.split("-")
            if len(parts) > 2:
                phone_number = "+" + parts[-1]

        # Create a call log entry (defaults to failed until the agent marks it successful)
        call_id = db.create_call_log()

        # Initialize the Assistant instance
        agent_instance = Assistant(phone_number=phone_number, is_outbound=is_outbound, call_id=call_id)

        # Start the session, which initializes the voice pipeline and warms up the models
        await session.start(
            agent=agent_instance,
            room=ctx.room,
            room_options=room_io.RoomOptions(
                audio_input=room_io.AudioInputOptions(
                    noise_cancellation=lambda params: (
                        noise_cancellation.BVCTelephony()
                        if params.participant.kind
                        == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                        else noise_cancellation.BVC()
                    ),
                ),
            ),
        )
        # logger.debug("[START] session.start() completed successfully")
    except Exception as e:
        # logger.error("[START] session.start() FAILED: %s", e)
        # logger.error("[START] Traceback:\n%s", traceback.format_exc())
        raise

    # ── DEBUG: Room connect ─────────────────────────────────────────────
    # logger.debug("[CONNECT] Calling ctx.connect() — joining room...")
    try:
        # Join the room and connect to the user
        await ctx.connect()

        @ctx.room.on("disconnected")
        def on_disconnected(*args, **kwargs):
            logger.info("Room disconnected. Triggering post-call WhatsApp follow-up.")
            call_summary = getattr(agent_instance, 'call_summary', "")
            scheduled_time = getattr(agent_instance, 'scheduled_callback_time', None)
            send_post_call_summary(phone_number, call_summary, scheduled_time)

        import asyncio
        async def delayed_greeting():
            await asyncio.sleep(1.5)
            try:
                if is_outbound:
                    await session.say(
                        "Hello! We noticed you might be interested in taking your business online. "
                        "Are you looking to build an e-commerce website?",
                        allow_interruptions=True,
                    )
                else:
                    await session.say("Hello! Are you looking to build a website?", allow_interruptions=True)
            except RuntimeError as e:
                logger.info("Skipped initial greeting: %s", e)

        @ctx.room.on("participant_connected")
        def on_participant_connected(participant: rtc.RemoteParticipant):
            if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
                logger.info(f"SIP Participant {participant.identity} joined. Grieeting them in 1.5s.")
                asyncio.create_task(delayed_greeting())

        # Check if they are already in the room (race condition safety)
        sip_participant = next((p for p in ctx.room.remote_participants.values() if p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP), None)
        if sip_participant:
            asyncio.create_task(delayed_greeting())
        # logger.debug("[CONNECT] ctx.connect() completed — agent is now in the room")
    except Exception as e:
        # logger.error("[CONNECT] ctx.connect() FAILED: %s", e)
        # logger.error("[CONNECT] Traceback:\n%s", traceback.format_exc())
        raise

    # logger.debug("═" * 60)
    # logger.debug("[SESSION] Agent fully started and connected to room: %s", ctx.room.name)


if __name__ == "__main__":
    # logger.debug("[MAIN] Starting agent CLI...")
    cli.run_app(server)
