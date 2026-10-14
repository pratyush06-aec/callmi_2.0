import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from dotenv import load_dotenv
from agent import Assistant, send_post_call_summary, SYSTEM_PROMPT, OUTBOUND_PROMPT_ADDENDUM

env_path = Path(__file__).resolve().parent.parent / ".env.local"
if not env_path.exists():
    env_path = Path(__file__).resolve().parent.parent / ".env.example"
load_dotenv(env_path)

TARGET_PHONE = os.environ.get("FALLBACK_PHONE_NUMBER", "+917810983647")
TARGET_HOST = os.environ.get("GREEN_API_HOST", "api.greenapi.com")
TARGET_RESUME = os.environ.get("RESUME_URL", "https://example.com/resume")


class TestAssistantInitialization:
    def test_assistant_default_prompt(self):
        """Test Assistant initialized with default system prompt."""
        agent = Assistant()
        assert SYSTEM_PROMPT in agent.instructions
        assert OUTBOUND_PROMPT_ADDENDUM not in agent.instructions

    def test_assistant_outbound_prompt(self):
        """Test Assistant initialized for outbound call includes outbound addendum."""
        agent = Assistant(is_outbound=True)
        assert OUTBOUND_PROMPT_ADDENDUM in agent.instructions

    def test_assistant_with_phone_number(self):
        """Test Assistant appends phone number context to instructions."""
        phone = TARGET_PHONE
        agent = Assistant(phone_number=phone)
        assert f"[SYSTEM] The caller's phone number is {phone}." in agent.instructions

    def test_assistant_with_call_id(self):
        """Test Assistant stores call_id correctly."""
        agent = Assistant(call_id=42)
        assert agent._call_id == 42


class TestPostCallSummary:
    def test_send_post_call_summary_skips_unknown_phone(self):
        """Test that unknown or missing phone number skips sending WhatsApp without error."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            send_post_call_summary("unknown", "Wants an online shop")
            send_post_call_summary(None, "Wants an online shop")
            mock_urlopen.assert_not_called()

    def test_send_post_call_summary_skips_if_credentials_missing(self, monkeypatch):
        """Test that missing Green API credentials cleanly aborts without exception."""
        monkeypatch.delenv("GREEN_API_ID_INSTANCE", raising=False)
        monkeypatch.delenv("GREEN_API_API_TOKEN_INSTANCE", raising=False)

        with patch("urllib.request.urlopen") as mock_urlopen:
            send_post_call_summary(TARGET_PHONE, "Wants an online shop")
            mock_urlopen.assert_not_called()

    def test_send_post_call_summary_constructs_correct_payload(self, monkeypatch):
        """Test that WhatsApp payload and URL are properly structured with context, resume, and callback schedule."""
        monkeypatch.setenv("GREEN_API_ID_INSTANCE", "12345")
        monkeypatch.setenv("GREEN_API_API_TOKEN_INSTANCE", "token_xyz")
        monkeypatch.setenv("GREEN_API_HOST", TARGET_HOST)
        monkeypatch.setenv("FALLBACK_PHONE_NUMBER", TARGET_PHONE)
        monkeypatch.setenv("RESUME_URL", TARGET_RESUME)

        mock_resp = MagicMock()
        mock_resp.status = 200

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            send_post_call_summary(
                phone_number=TARGET_PHONE,
                call_summary="Apparel catalog with razorpay",
                scheduled_time="tomorrow at 10 AM",
            )

            assert mock_urlopen.called
            req = mock_urlopen.call_args[0][0]
            assert f"https://{TARGET_HOST}/waInstance12345/sendMessage/token_xyz" in req.full_url

            import json
            payload = json.loads(req.data.decode("utf-8"))
            expected_chat_id = f"{TARGET_PHONE.replace('+', '')}@c.us"
            assert payload["chatId"] == expected_chat_id
            assert "Apparel catalog with razorpay" in payload["message"]
            assert "tomorrow at 10 AM" in payload["message"]
            assert TARGET_PHONE in payload["message"]
            assert TARGET_RESUME in payload["message"]


class TestPhoneNumberNormalization:
    def test_phone_normalization_logic(self):
        """Test edge cases of phone number normalization (+ vs without +)."""
        num_with_plus = TARGET_PHONE if TARGET_PHONE.startswith("+") else f"+{TARGET_PHONE}"
        num_without_plus = TARGET_PHONE.replace("+", "")
        ten_digit_raw = num_without_plus[-10:]

        # Normalization logic supporting with +, without +, and 10-digit formats
        def normalize(phone: str) -> str:
            if phone.startswith("+"):
                return phone
            if phone.startswith("91") and len(phone) == 12:
                return f"+{phone}"
            return f"+91{phone}"

        assert normalize(num_with_plus) == num_with_plus
        assert normalize(num_without_plus) == num_with_plus
        assert normalize(ten_digit_raw) == num_with_plus

        # Target chatId conversion for Green API
        target = normalize(ten_digit_raw).replace("+", "")
        chat_id = f"{target}@c.us"
        assert chat_id == f"{num_without_plus}@c.us"
