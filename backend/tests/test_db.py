import os
import tempfile
import sqlite3
import pytest
from pathlib import Path
from dotenv import load_dotenv
import db

env_path = Path(__file__).resolve().parent.parent / ".env.local"
if not env_path.exists():
    env_path = Path(__file__).resolve().parent.parent / ".env.example"
load_dotenv(env_path)

TARGET_PHONE = os.environ.get("FALLBACK_PHONE_NUMBER", "+919635480094")


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    """Create a temporary database for isolated testing of db.py functions."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    db.init_db()

    yield temp_db_path

    if os.path.exists(temp_db_path):
        try:
            os.remove(temp_db_path)
        except OSError:
            pass


class TestDatabaseSchema:
    def test_init_db_creates_all_tables(self, temp_db):
        """Test that init_db creates all required tables idempotently."""
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cursor.fetchall()}

        expected_tables = {"users", "escalations", "call_logs", "discovery_details", "callbacks"}
        assert expected_tables.issubset(tables)

    def test_init_db_idempotency(self, temp_db):
        """Test that calling init_db multiple times does not raise or corrupt tables."""
        db.init_db()
        db.init_db()


class TestCallerOperations:
    def test_upsert_and_get_caller_with_dict_facts(self):
        """Test saving and retrieving caller data with dictionary facts."""
        user_id = TARGET_PHONE
        facts = {"company": "Acme Corp", "interest": "Shopify store"}

        db.upsert_caller(user_id, "John Doe", "en-IN", facts)
        caller = db.get_caller(user_id)

        assert caller is not None
        assert caller["user_id"] == user_id
        assert caller["name"] == "John Doe"
        assert caller["language_preference"] == "en-IN"
        assert caller["facts"] == facts

    def test_upsert_and_get_caller_with_string_facts(self):
        """Test saving facts as JSON string."""
        user_id = "+918888888888"
        facts_str = '{"budget": "5000 USD", "timeline": "2 weeks"}'

        db.upsert_caller(user_id, "Jane", "hi-IN", facts_str)
        caller = db.get_caller(user_id)

        assert caller is not None
        assert caller["facts"] == {"budget": "5000 USD", "timeline": "2 weeks"}

    def test_upsert_caller_updates_on_conflict(self):
        """Test that inserting an existing user_id updates the existing record."""
        user_id = "+917777777777"
        db.upsert_caller(user_id, "Original Name", "en-IN", {"level": 1})
        db.upsert_caller(user_id, "Updated Name", "te-IN", {"level": 2})

        caller = db.get_caller(user_id)
        assert caller["name"] == "Updated Name"
        assert caller["language_preference"] == "te-IN"
        assert caller["facts"] == {"level": 2}

    def test_get_caller_nonexistent_returns_none(self):
        """Test querying an unknown caller returns None."""
        assert db.get_caller("+910000000000") is None

    def test_get_caller_handles_corrupt_json_gracefully(self, temp_db):
        """Test that corrupt non-JSON strings in facts do not crash get_caller."""
        user_id = "+911111111111"
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (user_id, name, language_preference, facts, last_interaction) VALUES (?, ?, ?, ?, ?)",
                (user_id, "Corrupt", "en-IN", "NOT_JSON_DATA{{{", "2026-01-01T00:00:00"),
            )
            conn.commit()

        caller = db.get_caller(user_id)
        assert caller is not None
        assert caller["facts"] == {}


class TestCallLogs:
    def test_create_and_update_call_log(self):
        """Test creating a default failed call log and marking it successful."""
        call_id = db.create_call_log()
        assert call_id is not None

        stats_initial = db.get_call_stats()
        assert stats_initial["total"] >= 1
        assert stats_initial["failed"] >= 1

        db.update_call_log(call_id, successful=True, reason="Lead qualified successfully")

        stats_updated = db.get_call_stats()
        assert stats_updated["successful"] >= 1

    def test_get_call_stats_aggregates_correctly(self):
        """Test accurate calculation of total, successful, and failed calls."""
        c1 = db.create_call_log()
        c2 = db.create_call_log()
        c3 = db.create_call_log()

        db.update_call_log(c1, successful=True, reason="Interested")
        db.update_call_log(c2, successful=False, reason="Wrong number")
        # c3 left as default failed (0)

        stats = db.get_call_stats()
        assert stats["total"] == 3
        assert stats["successful"] == 1
        assert stats["failed"] == 2


class TestDiscoveryDetails:
    def test_upsert_discovery_details_insert_and_update(self):
        """Test inserting and updating discovery details for a lead."""
        phone = TARGET_PHONE
        db.upsert_discovery_details(
            phone_number=phone,
            budget="$3000",
            products="Organic tea",
            timeline="1 month",
            features="Payment gateway, subscription billing",
        )

        with sqlite3.connect(db.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.cursor().execute("SELECT * FROM discovery_details WHERE phone_number = ?", (phone,)).fetchone()
            assert row is not None
            assert row["budget"] == "$3000"
            assert row["products"] == "Organic tea"
            assert row["timeline"] == "1 month"
            assert row["features"] == "Payment gateway, subscription billing"

        # Update existing record
        db.upsert_discovery_details(
            phone_number=phone,
            budget="$5000",
            products="Organic tea & accessories",
            timeline="Immediate",
            features="Payment gateway, multi-currency",
        )

        with sqlite3.connect(db.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            updated_row = conn.cursor().execute("SELECT * FROM discovery_details WHERE phone_number = ?", (phone,)).fetchone()
            assert updated_row["budget"] == "$5000"
            assert updated_row["products"] == "Organic tea & accessories"
            assert updated_row["timeline"] == "Immediate"


class TestCallbacksAndEscalations:
    def test_schedule_callback(self):
        """Test storing a scheduled callback request."""
        phone = TARGET_PHONE
        spoken_time = "tomorrow afternoon at 3 PM"
        parsed_iso = "2026-10-15T15:00:00"

        db.schedule_callback(phone, spoken_time, parsed_iso)

        with sqlite3.connect(db.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.cursor().execute("SELECT * FROM callbacks WHERE phone_number = ?", (phone,)).fetchone()
            assert row is not None
            assert row["spoken_time"] == spoken_time
            assert row["parsed_iso_time"] == parsed_iso

    def test_create_escalation_record(self):
        """Test recording an escalation request."""
        db.create_escalation_record(
            reference_id="ESC-101",
            phone_number=TARGET_PHONE,
            who_needs_help="Store owner",
            what_happened="Needs enterprise migration quote",
            agent_checked="Checked Shopify Plus requirements",
            urgency="High",
            language_followup="English",
        )

        with sqlite3.connect(db.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.cursor().execute("SELECT * FROM escalations WHERE reference_id = ?", ("ESC-101",)).fetchone()
            assert row is not None
            assert row["who_needs_help"] == "Store owner"
            assert row["urgency"] == "High"
