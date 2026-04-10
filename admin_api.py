"""
admin_api.py  –  LogiBot Admin Dashboard API
Run alongside your Rasa server:  python admin_api.py
Serves on  http://localhost:5050
"""

from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
from actions.db_helper import get_conn, close_session, log_chat
from datetime import datetime, timedelta

app = Flask(__name__)

# Allow both common dev origins; credentials not needed so omit that.
CORS(app, resources={r"/*": {
    "origins": ["http://127.0.0.1:5500", "http://localhost:5500", "http://localhost:3000"],
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": ["Content-Type"],
}})


@app.route("/log_chat", methods=["POST", "OPTIONS"])
def log_chat_api():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data = request.get_json(force=True)
        session_id = data.get("session_id")
        message    = data.get("message")
        role       = data.get("role")
        intent     = data.get("intent")
        confidence = data.get("confidence")

        if session_id and message:
            log_chat(session_id, message, role, intent, confidence)

        return jsonify({"status": "logged"}), 200

    except Exception as e:
        print("❌ LOG CHAT ERROR:", e)
        return jsonify({"error": str(e)}), 500


def _q(sql, params=()):
    """Run a SELECT, return list-of-dicts."""
    try:
        with get_conn() as (conn, cur):
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception as e:
        print("DB ERROR:", e)
        return []


def _q1(sql, params=()):
    """Run a SELECT, return single row or {}."""
    rows = _q(sql, params)
    return rows[0] if rows else {}


# ── /api/stats  ─────────────────────────────────────────────────────────────
@app.route("/api/stats")
def stats():
    totals = _q("""
        SELECT 'bookings'  AS tbl, COUNT(*) AS cnt FROM bookings  UNION ALL
        SELECT 'pickups'            , COUNT(*)      FROM pickups   UNION ALL
        SELECT 'sessions'           , COUNT(*)      FROM sessions  UNION ALL
        SELECT 'chat_logs'          , COUNT(*)      FROM chat_logs UNION ALL
        SELECT 'active_sessions'    , COUNT(*)      FROM sessions  WHERE end_time IS NULL
    """)
    result = {r["tbl"]: int(r["cnt"]) for r in totals}

    dur = _q1("""
        SELECT AVG(TIMESTAMPDIFF(SECOND, start_time, end_time)) AS avg_sec
        FROM sessions WHERE end_time IS NOT NULL
    """)
    result["avg_session_sec"] = round(float(dur.get("avg_sec") or 0))

    today = _q("""
        SELECT 'bookings_today' AS k, COUNT(*) AS v FROM bookings  WHERE DATE(booked_at)    = CURDATE() UNION ALL
        SELECT 'pickups_today'      , COUNT(*)       FROM pickups   WHERE DATE(scheduled_at) = CURDATE() UNION ALL
        SELECT 'sessions_today'     , COUNT(*)       FROM sessions  WHERE DATE(start_time)   = CURDATE() UNION ALL
        SELECT 'messages_today'     , COUNT(*)       FROM chat_logs WHERE DATE(timestamp)    = CURDATE()
    """)
    result.update({r["k"]: int(r["v"]) for r in today})

    return jsonify(result)


# ── /api/sessions  ──────────────────────────────────────────────────────────
@app.route("/api/sessions")
def sessions():
    rows = _q("""
        SELECT
            s.session_id,
            s.user_id,
            s.start_time,
            s.end_time,
            TIMESTAMPDIFF(SECOND, s.start_time,
                IFNULL(s.end_time, NOW())) AS duration_sec,
            COUNT(cl.log_id) AS message_count
        FROM sessions s
        LEFT JOIN chat_logs cl ON cl.session_id = s.session_id
        GROUP BY s.session_id, s.start_time, s.end_time
        ORDER BY s.start_time DESC
        LIMIT 50
    """)
    for r in rows:
        r["start_time"]   = r["start_time"].isoformat() if r["start_time"] else None
        r["end_time"]     = r["end_time"].isoformat()   if r["end_time"]   else None
        r["duration_sec"] = int(r["duration_sec"] or 0)
        r["message_count"] = int(r["message_count"] or 0)
    return jsonify(rows)


# ── /end-session  ────────────────────────────────────────────────────────────
@app.route("/end-session", methods=["POST", "OPTIONS"])
def end_session():
    # flask-cors handles OPTIONS automatically, but being explicit is safe
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data = request.get_json(force=True)
        session_id = data.get("session_id")

        if session_id:
            close_session(session_id)
            print(f"✅ Session closed: {session_id}")

        return jsonify({"status": "closed"}), 200

    except Exception as e:
        print("❌ END SESSION ERROR:", e)
        return jsonify({"error": str(e)}), 500


# ── /api/bookings  ──────────────────────────────────────────────────────────
@app.route("/api/bookings")
def bookings():
    rows = _q("""
        SELECT booking_id, sender_name, sender_number, sender_email,
               receiver_name, receiver_number, delivery_address, cost, booked_at
        FROM bookings
        ORDER BY booked_at DESC
        LIMIT 50
    """)
    for r in rows:
        r["booked_at"] = r["booked_at"].isoformat() if r["booked_at"] else None
        r["cost"] = float(r["cost"] or 0)
    return jsonify(rows)


# ── /api/pickups  ───────────────────────────────────────────────────────────
@app.route("/api/pickups")
def pickups():
    rows = _q("""
        SELECT pickup_id, name, contact, address,
               pickup_date, pickup_time, scheduled_at
        FROM pickups
        ORDER BY scheduled_at DESC
        LIMIT 50
    """)
    for r in rows:
        r["scheduled_at"] = r["scheduled_at"].isoformat() if r["scheduled_at"] else None
        r["pickup_date"]  = str(r["pickup_date"])  if r["pickup_date"]  else None
        r["pickup_time"]  = str(r["pickup_time"])  if r["pickup_time"]  else None
    return jsonify(rows)


# ── /api/chatlogs  ──────────────────────────────────────────────────────────
@app.route("/api/chatlogs")
def chatlogs():
    session_id = request.args.get("session_id")

    if session_id:
        rows = _q("""
            SELECT log_id, session_id, role, message, intent, confidence, timestamp
            FROM chat_logs
            WHERE session_id = %s
            ORDER BY timestamp ASC
        """, (session_id,))
    else:
        rows = _q("""
            SELECT log_id, session_id, role, message, intent, confidence, timestamp
            FROM chat_logs
            ORDER BY timestamp DESC
            LIMIT 100
        """)

    for r in rows:
        r["timestamp"]  = r["timestamp"].isoformat() if r["timestamp"] else None
        r["confidence"] = float(r["confidence"]) if r["confidence"] else None

    return jsonify(rows)


# ── /api/intents  ───────────────────────────────────────────────────────────
@app.route("/api/intents")
def intents():
    rows = _q("""
        SELECT intent, COUNT(*) AS cnt
        FROM chat_logs
        WHERE intent IS NOT NULL AND intent != ''
        GROUP BY intent
        ORDER BY cnt DESC
        LIMIT 10
    """)
    for r in rows:
        r["cnt"] = int(r["cnt"])
    return jsonify(rows)


# ── /api/daily  ─────────────────────────────────────────────────────────────
@app.route("/api/daily")
def daily():
    rows = _q("""
        SELECT DATE(start_time) AS day, COUNT(*) AS sessions
        FROM sessions
        WHERE start_time >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
        GROUP BY DATE(start_time)
        ORDER BY day
    """)
    for r in rows:
        r["day"]      = str(r["day"])
        r["sessions"] = int(r["sessions"])
    return jsonify(rows)


if __name__ == "__main__":
    app.run(port=5050, debug=False)