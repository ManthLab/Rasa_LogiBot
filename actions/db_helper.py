
import mysql.connector
from mysql.connector import pooling
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="logibot_pool",
            pool_size=5,
            host="localhost",
            user="root",
            password="12345",
            database="logibot_db",
            charset="utf8mb4",
            autocommit=True,           
        )
    return _pool


def get_conn():
    """Get a connection from the pool. Always use as a context manager:
       with get_conn() as conn: ...
    """
    return _get_conn_ctx()


class _get_conn_ctx:
    """Context manager that borrows a connection from the pool
    and returns it automatically when the block exits."""

    def __enter__(self):
        self.conn = _get_pool().get_connection()
        self.cursor = self.conn.cursor(dictionary=True)
        return self.conn, self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                self.conn.rollback()
            self.cursor.close()
        finally:
            self.conn.close()           
        return False                    

#------------------ SESSION HELPERS ------------------

def ensure_session(session_id: str) -> None:
    """Create session row if it doesn't exist yet.
    Safe to call on every action — INSERT IGNORE skips duplicates."""
    try:
        with get_conn() as (conn, cur):
            cur.execute(
                "INSERT IGNORE INTO sessions (session_id) VALUES (%s)",
                (session_id,)
            )
    except Exception as e:
        logger.error("ensure_session error: %s", e)


def close_session(session_id: str) -> None:
    """Mark session as ended (call on ActionSessionStart for new convo)."""
    try:
        with get_conn() as (conn, cur):
            cur.execute(
                "UPDATE sessions SET end_time = %s WHERE session_id = %s AND end_time IS NULL",
                (datetime.now(), session_id)
            )
    except Exception as e:
        logger.error("close_session error: %s", e)

#----------------- CHAT LOG -----------------
def log_chat(
    session_id: str,
    user_message: str,
    bot_response: str,
    intent: str,
    confidence: float = None,
) -> None:
    """
    Insert one conversation turn into chat_logs.
    Call this at the end of every action's run() method.

    Usage in actions.py:
        from db_helper import log_chat, ensure_session
        ensure_session(tracker.sender_id)
        log_chat(
            session_id   = tracker.sender_id,
            user_message = tracker.latest_message.get("text"),
            bot_response = response,        # the string you built
            intent       = tracker.latest_message.get("intent", {}).get("name"),
            confidence   = tracker.latest_message.get("intent", {}).get("confidence"),
        )
    """
    try:
        ensure_session(session_id)
        with get_conn() as (conn, cur):
            cur.execute(
                """
                INSERT INTO chat_logs
                    (session_id, user_message, bot_response, intent, confidence)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (session_id, user_message, bot_response, intent, confidence)
            )
    except Exception as e:
        logger.error("log_chat error: %s", e)


#----------------- TRACKING -----------------------

def get_tracking(tracking_id: str) -> dict | None:
    """Return tracking row as dict, or None if not found."""
    try:
        with get_conn() as (conn, cur):
            cur.execute(
                "SELECT * FROM tracking WHERE tracking_id = %s",
                (tracking_id.strip().upper(),)
            )
            return cur.fetchone()
    except Exception as e:
        logger.error("get_tracking error: %s", e)
        return None

#----------------------- BOOKINGS ---------------------

def insert_booking(
    booking_id: str,
    sender_name: str,
    sender_number: str,
    sender_email: str,
    receiver_name: str,
    receiver_number: str,
    delivery_address: str,
    cost: float,
) -> bool:
    """
    Insert a new booking row.
    Returns True on success, False on failure.

    Usage in ActionBookShipment.run():
        success = insert_booking(
            booking_id, sender, sender_number, sender_email,
            receiver, receiver_number, full_address, total_cost
        )
    """
    try:
        with get_conn() as (conn, cur):
            # NEW — explicitly pass NOW() so timestamp is never NULL
            cur.execute(
                """
                INSERT INTO bookings
                    (booking_id, sender_name, sender_number, sender_email,
                     receiver_name, receiver_number, delivery_address, cost, booked_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (booking_id, sender_name, sender_number, sender_email,
                 receiver_name, receiver_number, delivery_address, cost)
            )
        return True
    except Exception as e:
        logger.error("insert_booking error: %s", e)
        return False

#--------------------- PICKUPS ---------------------


def insert_pickup(
    pickup_id: str,
    name: str,
    contact: str,
    address: str,
    pickup_date: str,  
    pickup_time: str,   
) -> bool:
    """
    Insert a new pickup row.
    Returns True on success, False on failure.

    Usage in ActionSchedulePickup.run():
        success = insert_pickup(
            pickup_id, name, contact, address, date, time
        )
    """
    try:
        # Parse date string → MySQL DATE format (YYYY-MM-DD)
        try:
            parsed_date = datetime.strptime(pickup_date, "%d %b %Y").strftime("%Y-%m-%d")
        except ValueError:
            parsed_date = None          
        try:
            parsed_time = datetime.strptime(pickup_time, "%I:%M %p").strftime("%H:%M:%S")
        except ValueError:
            parsed_time = None

        with get_conn() as (conn, cur):
            cur.execute(
                """
                INSERT INTO pickups
                    (pickup_id, name, contact, address,
                     pickup_date, pickup_time, scheduled_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (pickup_id, name, contact, address,
                 parsed_date, parsed_time, datetime.now())
            )
        return True
    except Exception as e:
        logger.error("insert_pickup error: %s", e)
        return False

#------------------------- BRANCHES -------------------------

def get_branch(city_key: str) -> dict | None:
    """
    Fetch branch info by city key (e.g. 'mumbai', 'delhi').
    Returns dict with address/phone/email/working_hours, or None.

    Usage in ActionNearestBranch.run():
        branch = get_branch(city_key)
        if branch:
            dispatcher.utter_message(text=f"Address: {branch['address']}")
    """
    try:
        with get_conn() as (conn, cur):
            cur.execute(
                "SELECT * FROM branches WHERE LOWER(city) = %s",
                (city_key.lower().strip(),)
            )
            return cur.fetchone()
    except Exception as e:
        logger.error("get_branch error: %s", e)
        return None