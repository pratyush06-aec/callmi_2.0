import sqlite3
import json
from datetime import datetime
import logging

logger = logging.getLogger("db")
DB_PATH = "caller_data.db"

def init_db():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    name TEXT,
                    language_preference TEXT,
                    facts TEXT,
                    last_interaction DATETIME
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS escalations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reference_id TEXT,
                    phone_number TEXT,
                    who_needs_help TEXT,
                    what_happened TEXT,
                    agent_checked TEXT,
                    urgency TEXT,
                    language_followup TEXT,
                    timestamp DATETIME
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS call_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    successful INTEGER DEFAULT 0,
                    reason TEXT DEFAULT '',
                    timestamp DATETIME
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS discovery_details (
                    phone_number TEXT PRIMARY KEY,
                    budget TEXT,
                    products TEXT,
                    timeline TEXT,
                    features TEXT,
                    last_updated DATETIME
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS callbacks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone_number TEXT,
                    spoken_time TEXT,
                    parsed_iso_time TEXT,
                    created_at DATETIME
                )
            ''')
            conn.commit()
    except Exception as e:
        logger.error("Failed to initialize database: %s", e)

def get_caller(user_id: str) -> dict | None:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            if row:
                data = dict(row)
                if data.get('facts'):
                    try:
                        data['facts'] = json.loads(data['facts'])
                    except:
                        data['facts'] = {}
                return data
            return None
    except Exception as e:
        logger.error("Failed to fetch caller data: %s", e)
        return None

def upsert_caller(user_id: str, name: str, language_preference: str, facts: str | dict):
    try:
        if isinstance(facts, dict):
            facts_str = json.dumps(facts)
        else:
            facts_str = facts

        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (user_id, name, language_preference, facts, last_interaction)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    name = excluded.name,
                    language_preference = excluded.language_preference,
                    facts = excluded.facts,
                    last_interaction = excluded.last_interaction
            ''', (user_id, name, language_preference, facts_str, now))
            conn.commit()
    except Exception as e:
        logger.error("Failed to upsert caller data: %s", e)

def create_escalation_record(reference_id: str, phone_number: str, who_needs_help: str, what_happened: str, agent_checked: str, urgency: str, language_followup: str):
    try:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO escalations (reference_id, phone_number, who_needs_help, what_happened, agent_checked, urgency, language_followup, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (reference_id, phone_number, who_needs_help, what_happened, agent_checked, urgency, language_followup, now))
            conn.commit()
    except Exception as e:
        logger.error("Failed to create escalation record: %s", e)

def create_call_log() -> int | None:
    """Create a new call log entry (defaults to failed). Returns the call_id."""
    try:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO call_logs (successful, reason, timestamp)
                VALUES (0, '', ?)
            ''', (now,))
            conn.commit()
            return cursor.lastrowid
    except Exception as e:
        logger.error("Failed to create call log: %s", e)
        return None

def update_call_log(call_id: int, successful: bool, reason: str):
    """Update an existing call log with the outcome."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE call_logs SET successful = ?, reason = ? WHERE id = ?
            ''', (1 if successful else 0, reason, call_id))
            conn.commit()
    except Exception as e:
        logger.error("Failed to update call log: %s", e)

def get_call_stats() -> dict:
    """Return aggregate call stats: total, successful, failed."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM call_logs')
            total = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM call_logs WHERE successful = 1')
            successful = cursor.fetchone()[0]
            return {"total": total, "successful": successful, "failed": total - successful}
    except Exception as e:
        logger.error("Failed to get call stats: %s", e)
        return {"total": 0, "successful": 0, "failed": 0}

def upsert_discovery_details(phone_number: str, budget: str, products: str, timeline: str, features: str):
    """Save or update discovery details for a lead."""
    try:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO discovery_details (phone_number, budget, products, timeline, features, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(phone_number) DO UPDATE SET
                    budget = excluded.budget,
                    products = excluded.products,
                    timeline = excluded.timeline,
                    features = excluded.features,
                    last_updated = excluded.last_updated
            ''', (phone_number, budget, products, timeline, features, now))
            conn.commit()
    except Exception as e:
        logger.error("Failed to upsert discovery details: %s", e)

def schedule_callback(phone_number: str, spoken_time: str, parsed_iso_time: str):
    """Save a scheduled callback request."""
    try:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO callbacks (phone_number, spoken_time, parsed_iso_time, created_at)
                VALUES (?, ?, ?, ?)
            ''', (phone_number, spoken_time, parsed_iso_time, now))
            conn.commit()
    except Exception as e:
        logger.error("Failed to schedule callback: %s", e)
