"""
Outbound Call Trigger Script for Disaster Response Agent.

Usage:
    uv run python outbound_trigger.py +91XXXXXXXXXX

This script uses the LiveKit Server SDK to create a SIP participant,
which causes LiveKit to dial the given phone number via the configured
SIP outbound trunk (Twilio). When the callee answers, they are placed
into a LiveKit room where the disaster response agent (Pooja) greets them.
"""

import asyncio
import sys
import os
from pathlib import Path

from dotenv import load_dotenv
from livekit import api

# Load environment variables
env_path = Path(__file__).resolve().parent / ".env.local"
load_dotenv(env_path, override=True)


async def make_outbound_call(phone_number: str):
    """Initiate an outbound SIP call to the given phone number."""

    livekit_url = os.environ.get("LIVEKIT_URL")
    api_key = os.environ.get("LIVEKIT_API_KEY")
    api_secret = os.environ.get("LIVEKIT_API_SECRET")
    sip_trunk_id = os.environ.get("SIP_OUTBOUND_TRUNK_ID")

    if not all([livekit_url, api_key, api_secret, sip_trunk_id]):
        print("ERROR: Missing required environment variables.")
        print("Ensure LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, and SIP_OUTBOUND_TRUNK_ID are set in .env.local")
        sys.exit(1)

    # Normalize phone number
    if not phone_number.startswith("+"):
        phone_number = f"+91{phone_number}"

    room_name = f"outbound-sales-call-{phone_number.replace('+', '')}"

    print(f"╔══════════════════════════════════════════╗")
    print(f"║  OUTBOUND SALES CALL                     ║")
    print(f"╠══════════════════════════════════════════╣")
    print(f"║  Dialing: {phone_number:<30} ║")
    print(f"║  Room:    {room_name:<30} ║")
    # print(f"║  Trunk:   {sip_trunk_id[:20]+'...':<30} ║") # Commented out to prevent credential exposure in logs
    print(f"╚══════════════════════════════════════════╝")

    lk_api = api.LiveKitAPI(
        url=livekit_url,
        api_key=api_key,
        api_secret=api_secret,
    )

    try:
        # First, create an agent dispatch so the agent is ready in the room
        # before the callee picks up
        await lk_api.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name="my-agent",
                room=room_name,
            )
        )
        print("✓ Agent dispatched to room, waiting for agent to connect...")
        await asyncio.sleep(2)

        # Send a pre-call WhatsApp message using Green API
        green_api_id = os.environ.get("GREEN_API_ID_INSTANCE")
        green_api_token = os.environ.get("GREEN_API_API_TOKEN_INSTANCE")
        green_api_host = os.environ.get("GREEN_API_HOST")
        fallback_phone = os.environ.get("FALLBACK_PHONE_NUMBER")
        if green_api_id and green_api_token and green_api_host:
            import urllib.request
            import json
            url = f"https://{green_api_host}/waInstance{green_api_id}/sendMessage/{green_api_token}"
            target_wa = phone_number.replace("+", "")
            contact_msg = f", you can reach me at {fallback_phone}" if fallback_phone else ""
            payload = {
                "chatId": f"{target_wa}@c.us",
                "message": f"Hi, this is our AI assistant. I'm calling you from our automated routing line{contact_msg}."
            }
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                urllib.request.urlopen(req)
                print("✓ Pre-call WhatsApp message sent successfully.")
            except Exception as e:
                print(f"✗ Failed to send pre-call WhatsApp: {e}")

        # Now dial the phone number
        participant = await lk_api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=sip_trunk_id,
                sip_call_to=phone_number,
                room_name=room_name,
                participant_identity=phone_number,
                participant_name="Welfare Check Callee",
            )
        )
        print(f"✓ Call initiated! SIP Participant ID: {participant.participant_id}")
        print("  The phone should be ringing now...")
        print("  Press Ctrl+C to exit this script (the call continues independently).")

        # Keep the script alive so the user can see the status
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\nScript exited. The call may still be active in the LiveKit room.")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)
    finally:
        await lk_api.aclose()


if __name__ == "__main__":
    fallback_target = os.environ.get("FALLBACK_PHONE_NUMBER")
    target_number = sys.argv[1] if len(sys.argv) > 1 else fallback_target
    if not target_number:
        print("Error: Target phone number not provided and FALLBACK_PHONE_NUMBER is not set in environment.")
        sys.exit(1)
    asyncio.run(make_outbound_call(target_number))
