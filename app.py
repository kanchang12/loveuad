from flask import Flask, request, jsonify, send_file, render_template, make_response, send_from_directory, Response
from flask_cors import CORS
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.background import BackgroundScheduler

from PIL import Image
import io
import base64
import twilio
import qrcode
import logging
import os
import google.generativeai as genai
import json
from config import Config
from db_manager import DatabaseManager
from rag_pipeline import RAGPipeline
from encryption import encrypt_data, decrypt_data, generate_patient_code, hash_patient_code
from pii_filter import PIIFilter

# Initialize Flask app
app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
CORS(app, supports_credentials=True)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize database and RAG
db_manager = DatabaseManager()
rag_pipeline = RAGPipeline(db_manager)

# Create analytics tables on startup
def init_analytics_tables():
    """Create analytics tables if they don't exist"""
    try:
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS survey_responses (
                    id SERIAL PRIMARY KEY,
                    code_hash VARCHAR(64) NOT NULL,
                    completion_date DATE NOT NULL DEFAULT CURRENT_DATE,
                    result_bucket VARCHAR(10) NOT NULL CHECK (result_bucket IN ('Low', 'Medium', 'High')),
                    survey_day INTEGER NOT NULL CHECK (survey_day IN (30, 60, 90)),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(code_hash, survey_day)
                );
                CREATE INDEX IF NOT EXISTS idx_survey_completion_date ON survey_responses(completion_date);
                
                CREATE TABLE IF NOT EXISTS daily_active_users (
                    id SERIAL PRIMARY KEY,
                    event_date DATE NOT NULL,
                    event_hour INTEGER NOT NULL CHECK (event_hour >= 0 AND event_hour < 24),
                    launch_count INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(event_date, event_hour)
                );
                CREATE INDEX IF NOT EXISTS idx_dau_event_date ON daily_active_users(event_date);
                
                CREATE TABLE IF NOT EXISTS daily_launch_tracker (
                    id SERIAL PRIMARY KEY,
                    code_hash VARCHAR(64) NOT NULL,
                    launch_date DATE NOT NULL DEFAULT CURRENT_DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(code_hash, launch_date)
                );
                CREATE INDEX IF NOT EXISTS idx_tracker_launch_date ON daily_launch_tracker(launch_date);
            """)
            conn.commit()
            logger.info("✓ Analytics tables initialized")
    except Exception as e:
        logger.warning(f"Analytics tables already exist or error: {e}")

init_analytics_tables()


# ============================================
# ADD TO app.py - COMPLETE SAFETY & SUMMARY SYSTEM
# ============================================

# Copy this entire section and paste it AFTER your rag_pipeline initialization
# (around line 50-60, after: rag_pipeline = RAGPipeline(db_manager))

import json
from datetime import datetime
import google.generativeai as genai

# ============================================
# SAFETY FUNCTIONS
# ============================================

def check_safety_and_alert(user_message, code_hash, db_manager):
    """
    Check message safety and create admin alert if needed
    Returns: (is_safe: bool, crisis_response: str or None)
    """
    message_lower = user_message.lower()
    
    # Crisis keywords
    crisis_patterns = {
        'suicide': ['kill myself', 'suicide', 'end my life', 'want to die', 'better off dead',
                   'no reason to live', 'take my own life', 'suicidal', 'end it all'],
        'self_harm': ['cut myself', 'hurt myself', 'self harm', 'self-harm', 'burn myself',
                     'harm myself', 'cutting', 'burning myself'],
        'harm_others': ['kill him', 'kill her', 'harm the patient', 'hurt him', 'hurt her',
                       'going to hurt', 'want to kill', 'strangle', 'suffocate', 'kill them'],
        'abuse': ['hitting him', 'hitting her', 'beating them', 'locked them in', 
                 'withholding food', 'leaving them alone for days', 'neglecting',
                 'hitting the patient', 'slapping']
    }
    
    # Check each category
    for alert_type, keywords in crisis_patterns.items():
        matched_keywords = [kw for kw in keywords if kw in message_lower]
        
        if matched_keywords:
            # LOG TO DATABASE
            try:
                with db_manager.get_connection() as conn:
                    cur = conn.cursor()
                    
                    # Redact message - only first 100 chars
                    excerpt = user_message[:100] + '...' if len(user_message) > 100 else user_message
                    
                    # Insert alert
                    cur.execute("""
                        INSERT INTO safety_alerts 
                        (code_hash, alert_type, severity, user_message_excerpt, detected_keywords)
                        VALUES (%s, %s, 'critical', %s, %s)
                    """, (code_hash, alert_type, excerpt, matched_keywords))
                    
                    conn.commit()
                    logger.critical(f"🚨 SAFETY ALERT: {alert_type} - Code: {code_hash[:8]}...")
                    
            except Exception as e:
                logger.error(f"Failed to log safety alert: {e}")
            
            # Return crisis response
            crisis_response = get_crisis_response(alert_type)
            return (False, crisis_response)
    
    # Safe - no crisis detected
    return (True, None)


def get_crisis_response(alert_type):
    """Return appropriate crisis response based on alert type"""
    
    responses = {
        'suicide': """**I'm very concerned about what you've shared.**

🚨 **Please get immediate help:**

**In the UK:**
- **999** - Emergency services (if in immediate danger)
- **Samaritans: 116 123** (24/7, free to call)
- **Crisis Text Line: Text SHOUT to 85258**
- **NHS 111** - Press option 2 for mental health crisis team

**You don't have to face this alone.** These services are confidential and staffed by trained professionals who can help you right now.

I'm not equipped to support you with suicidal thoughts - please reach out to these services immediately.""",

        'self_harm': """**I'm concerned about what you've shared.**

🚨 **Please get support:**

**In the UK:**
- **Samaritans: 116 123** (24/7, confidential)
- **Mind: 0300 123 3393** (Mon-Fri 9am-6pm)
- **NHS 111** - Press 2 for mental health support
- **Your GP** - can arrange urgent mental health assessment

This chat isn't designed to support self-harm. Please speak to a trained professional who can help you safely.""",

        'harm_others': """**I need to be direct with you.**

If you're having thoughts about harming someone, please:

- **Call 999** if you feel you might act on these thoughts
- **Contact your GP immediately** for urgent mental health support
- **Samaritans: 116 123** to talk through these feelings confidentially

If the person you care for is in immediate danger, call 999 now.

I can't continue this conversation - please speak to a professional who can help you with these thoughts.""",

        'abuse': """**What you're describing sounds very serious.**

If someone is being harmed or neglected:

**Report immediately:**
- **Call 999** if there's immediate danger
- **Adult Safeguarding: 0300 500 80 80** (report concerns)
- **Action on Elder Abuse Helpline: 080 8808 8141**
- **Your local social services department**

This is beyond what this chat can help with. Please contact these services - they're confidential and trained to investigate and protect vulnerable adults."""
    }
    
    return responses.get(alert_type, "Please contact emergency services if you're in crisis.")


# ============================================
# DAILY SUMMARY FUNCTIONS
# ============================================

def save_daily_summary(code_hash, query, response, db_manager):
    """
    Save conversation summary for context continuity
    Called after each conversation
    """
    try:
        # Create summary using Gemini
        summary_prompt = f"""Summarize this caregiver conversation in 1-2 sentences. Focus on the main concern and emotion.

Caregiver said: {query}
Response given: {response[:300]}

Summary (1-2 sentences, conversational tone):"""
        
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        summary_response = model.generate_content(summary_prompt)
        summary = summary_response.text.strip()
        
        # Encrypt summary
        from encryption import encrypt_data
        encrypted_summary = encrypt_data({
            'summary': summary,
            'timestamp': datetime.now().isoformat()
        })
        
        # Save to database
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO chat_summaries (code_hash, encrypted_summary)
                VALUES (%s, %s)
                ON CONFLICT (code_hash, date) 
                DO UPDATE SET 
                    encrypted_summary = chat_summaries.encrypted_summary || ' | ' || EXCLUDED.encrypted_summary,
                    conversation_count = chat_summaries.conversation_count + 1
            """, (code_hash, encrypted_summary))
            conn.commit()
        
        logger.info(f"✓ Summary saved for {code_hash[:8]}...")
        
    except Exception as e:
        logger.error(f"Summary save failed: {e}")
        pass  # Don't fail main request


def get_conversation_context(code_hash, db_manager):
    """
    Get last 7 days of conversation summaries
    Returns formatted context string or None
    """
    try:
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT encrypted_summary, date
                FROM chat_summaries
                WHERE code_hash = %s
                AND date >= CURRENT_DATE - INTERVAL '7 days'
                ORDER BY date DESC
                LIMIT 7
            """, (code_hash,))
            
            rows = cur.fetchall()
        
        if not rows:
            return None
        
        # Decrypt and format
        from encryption import decrypt_data
        context_parts = []
        
        for row in rows:
            try:
                data = decrypt_data(row[0])  # encrypted_summary
                date = row[1]
                # Handle multiple summaries from same day (separated by ' | ')
                summaries = data['summary'].split(' | ') if ' | ' in data['summary'] else [data['summary']]
                for summary in summaries:
                    context_parts.append(f"- {date}: {summary}")
            except:
                continue
        
        if context_parts:
            return "**Recent conversations:**\n" + "\n".join(context_parts[:5])  # Max 5 most recent
        return None
        
    except Exception as e:
        logger.error(f"Context fetch failed: {e}")
        return None


# ============================================
# UPDATED /api/dementia/query ENDPOINT
# ============================================

# FIND your existing @app.route('/api/dementia/query', methods=['POST'])
# and REPLACE it with this:

@app.route('/api/dementia/query', methods=['POST'])
def dementia_query():
    """CBT coach endpoint with safety guardrails and context"""
    try:
        data = request.json
        code_hash = data.get('codeHash')
        query = data.get('query')
        
        if not code_hash or not query:
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Verify patient exists
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Invalid patient code'}), 404
        
        # ✅ STEP 1: SAFETY CHECK FIRST (before any AI processing)
        is_safe, crisis_response = check_safety_and_alert(query, code_hash, db_manager)
        
        if not is_safe:
            # CRITICAL ALERT - Return crisis response, NO AI processing
            return jsonify({
                'success': True,
                'answer': crisis_response,
                'sources': [],
                'safety_alert': True
            }), 200
        
        # ✅ STEP 2: Get conversation context (last 7 days)
        conversation_context = get_conversation_context(code_hash, db_manager)
        
        # ✅ STEP 3: Enhance query with context for RAG
        if conversation_context:
            enhanced_query = f"{conversation_context}\n\n**Today's question:** {query}"
        else:
            enhanced_query = query
        
        # ✅ STEP 4: Get RAG response
        rag_response = rag_pipeline.get_response(enhanced_query)
        
        # ✅ STEP 5: Save conversation summary (async - don't block)
        try:
            save_daily_summary(code_hash, query, rag_response['answer'], db_manager)
        except Exception as e:
            logger.error(f"Summary save error: {e}")
            pass  # Don't fail request if summary fails
        
        # ✅ STEP 6: Encrypt and store full conversation
        from encryption import encrypt_data
        encrypted_query = encrypt_data(query)
        encrypted_response = encrypt_data(rag_response['answer'])
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO conversations (code_hash, encrypted_query, encrypted_response, sources, created_at)
                VALUES (%s, %s, %s, %s, NOW())
            """, (code_hash, encrypted_query, encrypted_response, json.dumps(rag_response.get('sources', []))))
            conn.commit()
        
        return jsonify({
            'success': True,
            'answer': rag_response['answer'],
            'sources': rag_response.get('sources', []),
            'disclaimer': 'This is caregiving support only. Always consult healthcare professionals for medical decisions.'
        }), 200
    
    except Exception as e:
        logger.error(f"Query error: {e}", exc_info=True)
        return jsonify({'error': 'Query processing failed'}), 500


# ============================================
# ADMIN DASHBOARD ENDPOINTS
# ============================================

@app.route('/api/admin/safety-alerts', methods=['GET'])
def get_safety_alerts():
    """Get unresolved safety alerts for admin dashboard"""
    try:
        # Simple password check (add env var: ADMIN_PASSWORD)
        auth_header = request.headers.get('Authorization')
        admin_password = os.environ.get('ADMIN_PASSWORD', 'changeme123')
        
        if auth_header != f"Bearer {admin_password}":
            return jsonify({'error': 'Unauthorized'}), 401
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            # Get unresolved critical alerts
            cur.execute("""
                SELECT 
                    id,
                    LEFT(code_hash, 8) as code_prefix,  -- Only show first 8 chars
                    alert_type,
                    severity,
                    user_message_excerpt,
                    detected_keywords,
                    timestamp,
                    admin_viewed,
                    admin_notes
                FROM safety_alerts
                WHERE resolved = false
                ORDER BY 
                    CASE severity 
                        WHEN 'critical' THEN 1 
                        WHEN 'high' THEN 2 
                        ELSE 3 
                    END,
                    timestamp DESC
                LIMIT 100
            """)
            
            columns = [desc[0] for desc in cur.description]
            alerts = [dict(zip(columns, row)) for row in cur.fetchall()]
        
        return jsonify({
            'success': True,
            'alerts': alerts,
            'count': len(alerts)
        }), 200
        
    except Exception as e:
        logger.error(f"Safety alerts error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/safety-alerts/<int:alert_id>/resolve', methods=['POST'])
def resolve_safety_alert(alert_id):
    """Mark alert as resolved with admin notes"""
    try:
        # Auth check
        auth_header = request.headers.get('Authorization')
        admin_password = os.environ.get('ADMIN_PASSWORD', 'changeme123')
        
        if auth_header != f"Bearer {admin_password}":
            return jsonify({'error': 'Unauthorized'}), 401
        
        data = request.json
        admin_notes = data.get('notes', '')
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE safety_alerts
                SET 
                    resolved = true,
                    admin_viewed = true,
                    admin_notes = %s
                WHERE id = %s
            """, (admin_notes, alert_id))
            conn.commit()
        
        logger.info(f"✓ Alert {alert_id} resolved by admin")
        return jsonify({'success': True}), 200
        
    except Exception as e:
        logger.error(f"Resolve alert error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/safety-alerts/stats', methods=['GET'])
def get_safety_stats():
    """Get safety alert statistics"""
    try:
        # Auth check
        auth_header = request.headers.get('Authorization')
        admin_password = os.environ.get('ADMIN_PASSWORD', 'changeme123')
        
        if auth_header != f"Bearer {admin_password}":
            return jsonify({'error': 'Unauthorized'}), 401
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            # Get stats
            cur.execute("""
                SELECT 
                    COUNT(*) as total_alerts,
                    COUNT(*) FILTER (WHERE resolved = false) as unresolved,
                    COUNT(*) FILTER (WHERE severity = 'critical') as critical_count,
                    COUNT(*) FILTER (WHERE alert_type = 'suicide') as suicide_count,
                    COUNT(*) FILTER (WHERE alert_type = 'harm_others') as harm_others_count,
                    COUNT(*) FILTER (WHERE timestamp >= NOW() - INTERVAL '24 hours') as last_24h
                FROM safety_alerts
            """)
            
            row = cur.fetchone()
            stats = {
                'total_alerts': row[0],
                'unresolved': row[1],
                'critical_count': row[2],
                'suicide_count': row[3],
                'harm_others_count': row[4],
                'last_24h': row[5]
            }
        
        return jsonify({
            'success': True,
            'stats': stats
        }), 200
        
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return jsonify({'error': str(e)}), 500



@app.route('/service-worker.js')
def service_worker():
    response = make_response(
        send_from_directory('static', 'service-worker.js')
    )
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Cache-Control'] = 'no-cache'
    return response

# Initialize Gemini API
if not Config.GEMINI_API_KEY:
    logger.warning("⚠️ GEMINI_API_KEY not set - OCR and AI features will fail")
    vision_model = None
else:
    genai.configure(api_key=Config.GEMINI_API_KEY)
    vision_model = genai.GenerativeModel(Config.VISION_MODEL)

# PII Filter instance
pii_filter = PIIFilter()

# ==================== MEDICATION ALARMS ====================
# ADD THIS CODE TO YOUR app.py (after line 72)

@app.route('/alarm')
def alarm_page():
    return render_template('ALARM.html')

@app.route('/api/alarms', methods=['GET'])
def get_alarms():
    try:
        code_hash = request.args.get('code_hash')
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS medication_reminders (
                    id SERIAL PRIMARY KEY,
                    code_hash VARCHAR(64),
                    medication_name VARCHAR(200) NOT NULL,
                    time TIME NOT NULL,
                    followup_time TIME,
                    active BOOLEAN DEFAULT true,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    phone_number VARCHAR(20),
                    last_called TIMESTAMP,
                    daily_status VARCHAR(10) NOT NULL DEFAULT 'PENDING'
                )
            """)
            conn.commit()
            
            if code_hash:
                cur.execute("""
                    SELECT id, medication_name, time::text as time, active, code_hash, daily_status
                    FROM medication_reminders 
                    WHERE code_hash = %s
                    ORDER BY time
                """, (code_hash,))
            else:
                cur.execute("""
                    SELECT id, medication_name, time::text as time, active, code_hash, daily_status
                    FROM medication_reminders 
                    ORDER BY time
                """)
            
            alarms = cur.fetchall()
            return jsonify([dict(alarm) for alarm in alarms]), 200
    except Exception as e:
        logger.error(f"Get alarms error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/alarms/check', methods=['POST'])
def check_alarms():
    try:
        data = request.json
        current_time = data.get('time')
        code_hash = data.get('code_hash')
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            if code_hash:
                cur.execute("""
                    SELECT id, medication_name, time::text as time, code_hash, daily_status
                    FROM medication_reminders 
                    WHERE time::text LIKE %s || '%%' 
                    AND active = true
                    AND code_hash = %s
                """, (current_time, code_hash))
            else:
                cur.execute("""
                    SELECT id, medication_name, time::text as time, code_hash, daily_status
                    FROM medication_reminders 
                    WHERE time::text LIKE %s || '%%' 
                    AND active = true
                """, (current_time,))
            
            alarms = cur.fetchall()
            return jsonify([dict(alarm) for alarm in alarms]), 200
    except Exception as e:
        logger.error(f"Check alarms error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/alarms', methods=['POST'])
def add_alarm():
    try:
        data = request.json
        code_hash = data.get('code_hash')
        medication_name = data.get('medication_name')
        time = data.get('time')
        
        if not medication_name or not time:
            return jsonify({'error': 'medication_name and time required'}), 400
        
        # Calculate followup time (time + 10 minutes)
        from datetime import datetime, timedelta
        time_obj = datetime.strptime(time, '%H:%M')
        followup_obj = time_obj + timedelta(minutes=10)
        followup_time = followup_obj.strftime('%H:%M')
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            # Get phone
            cur.execute("SELECT encrypted_data FROM patients WHERE code_hash = %s", (code_hash,))
            patient = cur.fetchone()
            patient_data = decrypt_data(patient['encrypted_data'])
            phone_number = patient_data.get('phoneNumber', '')
            
            cur.execute("""
                INSERT INTO medication_reminders (code_hash, medication_name, time, followup_time, phone_number, active, daily_status)
                VALUES (%s, %s, %s, %s, %s, true, 'PENDING')
                RETURNING id
            """, (code_hash, medication_name, time, followup_time, phone_number))
            
            conn.commit()
            return jsonify({'success': True}), 201
    except Exception as e:
        logger.error(f"Add alarm error: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== PUSH SUBSCRIPTION MANAGEMENT ====================

@app.route('/api/push/subscribe', methods=['POST'])
def push_subscribe():
    """Save push notification subscription"""
    try:
        data = request.json
        code_hash = data.get('codeHash')
        subscription = data.get('subscription')
        
        if not code_hash or not subscription:
            return jsonify({'error': 'Missing required fields'}), 400
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            # Create table if not exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS push_subscriptions (
                    id SERIAL PRIMARY KEY,
                    code_hash VARCHAR(64) NOT NULL,
                    subscription_data TEXT NOT NULL,
                    active BOOLEAN DEFAULT true,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(code_hash, subscription_data)
                )
            """)
            
            # Insert or update subscription
            cur.execute("""
                INSERT INTO push_subscriptions (code_hash, subscription_data)
                VALUES (%s, %s)
                ON CONFLICT (code_hash, subscription_data) 
                DO UPDATE SET active = true
            """, (code_hash, json.dumps(subscription)))
            
            conn.commit()
        
        logger.info(f"Push subscription saved for {code_hash[:8]}...")
        return jsonify({'success': True}), 200
        
    except Exception as e:
        logger.error(f"Push subscribe error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/push/vapid-public-key', methods=['GET'])
def get_vapid_public_key():
    """Get VAPID public key for push notifications"""
    return jsonify({
        'publicKey': os.environ.get('VAPID_PUBLIC_KEY', '')
    }), 200

@app.route('/api/alarms/<int:alarm_id>', methods=['PUT'])
def update_alarm(alarm_id):
    try:
        data = request.json
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            updates = []
            values = []
            
            if 'medication_name' in data:
                updates.append("medication_name = %s")
                values.append(data['medication_name'])
            
            if 'time' in data:
                updates.append("time = %s")
                values.append(data['time'])
            
            if 'active' in data:
                updates.append("active = %s")
                values.append(data['active'])
            
            if not updates:
                return jsonify({'error': 'No fields to update'}), 400
            
            values.append(alarm_id)
            query = f"UPDATE medication_reminders SET {', '.join(updates)} WHERE id = %s RETURNING id"
            
            cur.execute(query, values)
            result = cur.fetchone()
            
            if not result:
                return jsonify({'error': 'Alarm not found'}), 404
            
            conn.commit()
            return jsonify({'success': True, 'id': alarm_id}), 200
    except Exception as e:
        logger.error(f"Update alarm error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/alarms/<int:alarm_id>', methods=['DELETE'])
def delete_alarm(alarm_id):
    try:
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            cur.execute("DELETE FROM medication_reminders WHERE id = %s RETURNING id", (alarm_id,))
            result = cur.fetchone()
            
            if not result:
                return jsonify({'error': 'Alarm not found'}), 404
            
            conn.commit()
            return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Delete alarm error: {e}")
        return jsonify({'error': str(e)}), 500


# ==================== PATIENT MANAGEMENT ====================

@app.route('/api/patient/register', methods=['POST', 'GET'])
def register_patient():
    """Register new patient with 17-character code"""
    try:
        data = request.json
        
        # Generate unique code (17-char format: XXXX-XXXX-XXXX-XXXX-X)
        patient_code = generate_patient_code()
        code_hash = hash_patient_code(patient_code)
        
        logger.info(f"Registering new patient - Code: {patient_code}, Hash: {code_hash[:10]}...")
        
        # Encrypt patient data with tier
        patient_data = {
            'firstName': data.get('firstName'),
            'lastName': data.get('lastName', ''),
            'age': data.get('age'),
            'gender': data.get('gender'),
            'phoneNumber': data.get('phoneNumber', ''),
            'tier': data.get('tier', 'premium'),  # Default to premium
            'createdAt': datetime.utcnow().isoformat()
        }
        
        encrypted_data = encrypt_data(patient_data)
        
        # Store in database
        db_manager.insert_patient_data(code_hash, encrypted_data, patient_data['phoneNumber'])
        
        logger.info(f"Patient registered successfully: {patient_data.get('firstName')}")
        
        return jsonify({
            'success': True,
            'patientCode': patient_code,
            'codeHash': code_hash,
            'tier': patient_data['tier']
        }), 201
    
    except Exception as e:
        logger.error(f"Registration error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Registration failed: {str(e)}'}), 500

@app.route('/patient/register', methods=['POST'])
def register_patient_noapi():
    return register_patient()

@app.route('/api/patient/login', methods=['POST', 'GET'])
def login_patient():
    """Login with patient code (17-character format: XXXX-XXXX-XXXX-XXXX-X)"""
    
    # -------------------------------------------------------------
    # FIX for 415 Unsupported Media Type / Handling GET/POST Data
    # -------------------------------------------------------------
    
    # 1. Initialize data dictionary
    data = {}
    
    # 2. Extract data based on request method and type
    if request.method == 'POST':
        # Attempt to get JSON data safely (handles 415 gracefully by returning None)
        data = request.get_json(silent=True)
        
        # If data extraction failed (None), try to load from request form or raw data
        if data is None:
            # Fallback for form data (application/x-www-form-urlencoded)
            data = request.form.to_dict()
            
            # Final fallback: try to load JSON manually from raw data (for bad content types)
            if not data and request.data:
                try:
                    data = json.loads(request.data)
                except (TypeError, json.JSONDecodeError):
                    # Data is unusable or not JSON/form, proceed with empty dict
                    data = {}
    
    elif request.method == 'GET':
        # For GET requests, parameters are in request.args
        data = request.args.to_dict()

    # 3. Handle missing data entirely
    if not data:
        logger.error("Login attempt with no usable data found.")
        return jsonify({'error': 'No patient code provided in the request body or parameters.'}), 400
        
    # -------------------------------------------------------------
    # Original Login Logic Resumes
    # -------------------------------------------------------------
    
    # Retrieve the code from the consolidated data dictionary
    patient_code = data.get('patientCode')
    
    try:
        if not patient_code:
            return jsonify({'error': 'Patient code required'}), 400
        
        # Clean and validate code format
        # NOTE: This uses the code sent over the network, which may be unformatted or formatted.
        clean_code = patient_code.replace('-', '').strip().upper()
        
        # Only accept 17-char format (XXXX-XXXX-XXXX-XXXX-X)
        if len(clean_code) != 17:
            logger.warning(f"Invalid code length: {len(clean_code)} chars (expected 17)")
            return jsonify({'error': f'Invalid code format. Expected 17 characters (XXXX-XXXX-XXXX-XXXX-X), got {len(clean_code)}'}), 400
        
        # NOTE: You should hash the CLEANED code, not the raw code, to ensure consistency.
        # Assuming hash_patient_code is designed to handle the 17-char code:
        code_hash = hash_patient_code(clean_code) 
        logger.info(f"Login attempt - Code: {patient_code}, Clean: {clean_code}, Hash: {code_hash[:10]}...")
        
        # Verify code exists
        patient = db_manager.get_patient_data(code_hash)
        
        if not patient:
            logger.warning(f"Patient not found - Clean Code Hash: {code_hash}")
            return jsonify({
                'error': 'Invalid patient code - not found in database. If you registered before, please register again with the new 17-character format.'
            }), 404
            
        # Decrypt patient data
        patient_data = decrypt_data(patient['encrypted_data'])
        
        if not patient_data:
            logger.error("Failed to decrypt patient data")
            return jsonify({'error': 'Data decryption failed'}), 500
            
        logger.info(f"Login successful for patient: {patient_data.get('firstName')}")
        
        return jsonify({
            'success': True,
            'codeHash': code_hash,
            'patient': {
                'firstName': patient_data.get('firstName'),
                'lastName': patient_data.get('lastName'),
                'age': patient_data.get('age'),
                'gender': patient_data.get('gender'),
                'tier': patient_data.get('tier', 'premium')
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}", exc_info=True)
        # Check if the error is the 415 exception being caught here
        if "Unsupported Media Type" in str(e):
             return jsonify({'error': 'Login failed due to incorrect request headers. Please contact support.'}), 415
        
        return jsonify({'error': f'Login failed: {str(e)}'}), 500

@app.route('/api/patient/qr/<code>', methods=['GET'])
def generate_qr(code):
    """Generate QR code for patient code"""
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(code)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        img_io = io.BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        
        return send_file(img_io, mimetype='image/png')
    
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        return jsonify({'error': 'QR generation failed'}), 500

# ==================== MEDICATION MANAGEMENT ====================

@app.route('/api/medications/add', methods=['POST'])
def add_medication():
    """Add medication for patient"""
    try:
        data = request.json
        code_hash = data.get('codeHash')
        medication = data.get('medication')
        
        if not code_hash or not medication:
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Verify patient exists
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Invalid patient code'}), 404
        
        # Add timestamp
        medication['createdAt'] = datetime.utcnow().isoformat()
        
        # Encrypt and store
        encrypted_data = encrypt_data(medication)
        db_manager.insert_medication(code_hash, encrypted_data)
        
        return jsonify({'success': True, 'message': 'Medication added'}), 201
    
    except Exception as e:
        logger.error(f"Add medication error: {e}")
        return jsonify({'error': 'Failed to add medication'}), 500

@app.route('/api/papers/count', methods=['GET'])
def get_papers_count():
    """Get total paper count"""
    try:
        stats = db_manager.get_stats()
        return jsonify({'success': True, 'totalPapers': stats['total_papers']}), 200
    except Exception as e:
        logger.error(f"Count error: {e}")
        return jsonify({'error': 'Failed'}), 500

@app.route('/api/papers/random', methods=['GET'])
def get_random_paper():
    """Get a random paper number"""
    try:
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT MAX(id) FROM research_papers;")
            max_id = cur.fetchone()['max']
        
        import random
        return jsonify({'success': True, 'paperId': random.randint(1, max_id)}), 200
    except Exception as e:
        logger.error(f"Random error: {e}")
        return jsonify({'error': 'Failed'}), 500

@app.route('/api/papers/<int:paper_id>', methods=['GET'])
def get_paper(paper_id):
    """Get paper by ID"""
    try:
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, title, authors, journal, year, doi, abstract, full_text, created_at
                FROM research_papers
                WHERE id = %s;
            """, (paper_id,))
            
            paper = cur.fetchone()
        
        if not paper:
            return jsonify({'error': 'Paper not found'}), 404
        
        result = {
            'paperId': paper['id'],
            'title': paper['title'] or 'Untitled',
            'authors': paper['authors'] or 'Unknown',
            'journal': paper['journal'] or 'N/A',
            'year': paper['year'] or 'N/A',
            'doi': paper['doi'] or 'N/A',
            'abstract': paper['abstract'] or '',
            'fullText': paper['full_text'] or '',
            'hasFullText': bool(paper['full_text']),
            'ingestedAt': paper['created_at']
        }
        
        return jsonify({'success': True, 'paper': result}), 200
    
    except Exception as e:
        logger.error(f"Get paper error: {e}")
        return jsonify({'error': 'Failed to fetch paper'}), 500

@app.route('/api/medications/<code_hash>', methods=['GET'])
def get_medications(code_hash):
    """Get all active medications for patient with today's adherence status"""
    try:
        medications = db_manager.get_medications(code_hash)
        
        decrypted_meds = [decrypt_data(med['encrypted_data']) for med in medications]
        
        # Get adherence data for today
        patient = db_manager.get_patient_data(code_hash)
        if patient:
            patient_data = decrypt_data(patient['encrypted_data'])
            adherence_history = patient_data.get('medicationAdherence', [])
            
            # Get today's date
            today = datetime.now().strftime('%Y-%m-%d')
            today_adherence = [a for a in adherence_history if a.get('date') == today]
            
            # Add adherence status to each medication time
            for med in decrypted_meds:
                if 'times' in med:
                    for i, time in enumerate(med['times']):
                        # Check if this medication at this time was taken today
                        taken = any(
                            a.get('medication') == med['name'] and 
                            a.get('scheduledTime') == time 
                            for a in today_adherence
                        )
                        # Add taken status to each time slot
                        if 'takenStatus' not in med:
                            med['takenStatus'] = {}
                        med['takenStatus'][time] = taken
        
        return jsonify({
            'success': True,
            'medications': decrypted_meds
        }), 200
    
    except Exception as e:
        logger.error(f"Get medications error: {e}")
        return jsonify({'error': 'Failed to fetch medications'}), 500

@app.route('/api/medications/update', methods=['POST'])
def update_medication():
    """Update medication in medications table AND medication_reminders table"""
    try:
        data = request.json
        code_hash = data.get('codeHash')
        medication = data.get('medication')
        
        if not code_hash or not medication:
            return jsonify({'error': 'Missing required fields'}), 400
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            # Get phone number
            cur.execute("SELECT phone_number FROM patients WHERE code_hash = %s", (code_hash,))
            patient = cur.fetchone()
            phone_number = patient['phone_number'] if patient else ''
            
            # Get ALL medication rows (same as get_medications does)
            cur.execute("SELECT id, encrypted_data FROM medications WHERE code_hash = %s", (code_hash,))
            all_med_rows = cur.fetchall()
            
            # Find the medication to update
            medication['updatedAt'] = datetime.utcnow().isoformat()
            updated = False
            
            for row in all_med_rows:
                existing_med = decrypt_data(row['encrypted_data'])
                if existing_med.get('name') == medication.get('name'):
                    # Update this specific row
                    encrypted_data = encrypt_data(medication)
                    cur.execute("""
                        UPDATE medications 
                        SET encrypted_data = %s 
                        WHERE id = %s
                    """, (encrypted_data, row['id']))
                    updated = True
                    break
            
            # If medication not found, insert it
            if not updated:
                encrypted_data = encrypt_data(medication)
                cur.execute("""
                    INSERT INTO medications (code_hash, encrypted_data, active)
                    VALUES (%s, %s, true)
                """, (code_hash, encrypted_data))
            
            # Update medication_reminders table
            cur.execute("""
                DELETE FROM medication_reminders 
                WHERE code_hash = %s AND medication_name = %s
            """, (code_hash, medication['name']))
            
            for time in medication.get('times', []):
                time_obj = datetime.strptime(time, '%H:%M')
                followup_obj = time_obj + timedelta(minutes=10)
                followup_time = followup_obj.strftime('%H:%M')
                
                cur.execute("""
                    INSERT INTO medication_reminders 
                    (code_hash, medication_name, time, followup_time, phone_number, active, daily_status)
                    VALUES (%s, %s, %s, %s, %s, true, 'PENDING')
                """, (code_hash, medication['name'], time, followup_time, phone_number))
            
            conn.commit()
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        logger.error(f"Update error: {e}")
        return jsonify({'error': str(e)}), 500


# ==================== PRESCRIPTION SCANNING ====================

@app.route('/api/scan/prescription', methods=['POST'])
def scan_prescription():
    """Scan prescription using Gemini Vision with PII filtering - NO DIAGNOSIS"""
    try:
        data = request.json
        image_data = data.get('image')
        code_hash = data.get('codeHash')
        
        if not image_data or not code_hash:
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Verify patient
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Invalid patient code'}), 404
        
        # Decode base64 image
        image_bytes = base64.b64decode(image_data.split(',')[1] if ',' in image_data else image_data)
        
        # OCR with Gemini Vision
        prompt = """Extract medication information from this prescription image.

Return ONLY the following information in this exact format:
Medication Name: [name]
Dosage: [dosage]
Frequency: [frequency]
Instructions: [instructions]

Do not include any patient names, addresses, or personal information."""
        
        # Convert bytes to PIL Image
        image = Image.open(io.BytesIO(image_bytes))
        response = vision_model.generate_content([prompt, image])
        
        ocr_text = response.text
        
        # Filter PII
        filtered_text = pii_filter.remove_pii(ocr_text)
        
        # AI Analysis with Gemini - NO DIAGNOSIS VERSION
        analysis_prompt = f"""Analyze this prescription and provide CAREGIVING GUIDANCE ONLY.

CRITICAL: You CANNOT diagnose conditions or interpret symptoms. You can ONLY provide:
- Medication management tips
- Safety information
- Storage guidance
- What healthcare professionals typically advise

Prescription Text:
{filtered_text}

Provide ONLY:
1. Medication summary (what it is commonly prescribed for - general info only)
2. Important safety warnings
3. Common considerations healthcare professionals mention
4. Storage instructions
5. Practical tips for dementia caregivers

DO NOT:
- Diagnose any condition
- Interpret why this was prescribed for this specific patient
- Make medical recommendations

Always end with: "Consult the prescribing doctor for questions about this medication."

Be concise and practical."""
        
        analysis_response = vision_model.generate_content(analysis_prompt)
        ai_analysis = analysis_response.text
        
        # Store as health record
        record_metadata = {
            'type': 'prescription_scan',
            'ocr_text': filtered_text,
            'ai_analysis': ai_analysis,
            'scanned_at': datetime.utcnow().isoformat()
        }
        
        encrypted_metadata = encrypt_data(record_metadata)
        db_manager.insert_health_record(code_hash, 'prescription', encrypted_metadata)
        
        return jsonify({
            'success': True,
            'ocr_text': filtered_text,
            'ai_analysis': ai_analysis,
            'disclaimer': '⚠️ This is NOT medical advice. Consult your healthcare provider for all medical questions.'
        }), 200
    
    except Exception as e:
        logger.error(f"Prescription scan error: {e}")
        return jsonify({'error': 'Scan failed'}), 500



# ==================== HEALTH RECORDS ====================

@app.route('/api/health/records/<code_hash>', methods=['GET'])
def get_health_records(code_hash):
    """Get health records for patient"""
    try:
        records = db_manager.get_health_records(code_hash)
        
        decrypted_records = [{
            'id': r['id'],
            'recordType': r['record_type'],
            'metadata': decrypt_data(r['encrypted_metadata']),
            'createdAt': r['created_at']
        } for r in records]
        
        return jsonify({
            'success': True,
            'records': decrypted_records
        }), 200
    
    except Exception as e:
        logger.error(f"Get health records error: {e}")
        return jsonify({'error': 'Failed to fetch records'}), 500

# ==================== CAREGIVER CONNECTIONS ====================

@app.route('/api/caregiver/connect', methods=['POST'])
def connect_caregiver():
    """Connect caregiver to patient"""
    try:
        data = request.json
        caregiver_id = data.get('caregiverId')
        patient_code = data.get('patientCode')
        patient_nickname = data.get('patientNickname')
        
        if not caregiver_id or not patient_code:
            return jsonify({'error': 'Missing required fields'}), 400
        
        code_hash = hash_patient_code(patient_code)
        
        # Verify patient exists
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Invalid patient code'}), 404
        
        # Create connection
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO caregiver_connections 
                (caregiver_id, code_hash, patient_nickname)
                VALUES (%s, %s, %s);
            """, (caregiver_id, code_hash, patient_nickname))
            conn.commit()
        
        return jsonify({'success': True}), 201
    
    except Exception as e:
        logger.error(f"Connection error: {e}")
        return jsonify({'error': 'Connection failed'}), 500

# ==================== DEMENTIA RAG ENDPOINTS ====================

@app.route('/api/dementia/queryold', methods=['POST', 'GET'])
def dementia_queryold():
    """Get dementia guidance with research citations - NO DIAGNOSIS"""
    try:
        data = request.json
        code_hash = data.get('codeHash')
        query = data.get('query')
        
        if not code_hash or not query:
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Verify patient exists
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Invalid patient code'}), 404
        
        # SAFETY CHECK: Detect diagnosis requests
        diagnosis_keywords = [
            'diagnose', 'diagnosis', 'what does he have', 'what does she have',
            'what condition', 'what disease', 'what is wrong', 'does he have',
            'does she have', 'is this', 'is it', 'could this be'
        ]
        
        query_lower = query.lower()
        is_diagnosis_request = any(keyword in query_lower for keyword in diagnosis_keywords)
        
        if is_diagnosis_request:
            # Return polite decline for diagnosis requests
            return jsonify({
                'success': True,
                'answer': """I cannot provide medical diagnoses. Only qualified healthcare professionals can diagnose conditions after proper examination.

**What I can help with:**
- Practical caregiving strategies
- Daily care tips
- Managing behaviors
- Communication techniques
- Safety recommendations

**What you should do:**
Please consult with your loved one's doctor or healthcare team. They can:
- Conduct proper medical assessments
- Order appropriate tests
- Provide accurate diagnosis
- Recommend treatment plans

Would you like practical caregiving advice instead?""",
                'sources': [],
                'disclaimer': '⚠️ This system does not diagnose medical conditions. Always consult healthcare professionals for medical decisions.'
            }), 200
        
        # Get RAG response with safety-enhanced prompt
        rag_response = rag_pipeline.get_response(query)
        
        # Encrypt and store conversation
        encrypted_query = encrypt_data(query)
        encrypted_response = encrypt_data(rag_response['answer'])
        
        db_manager.insert_conversation(
            code_hash,
            encrypted_query,
            encrypted_response,
            json.dumps(rag_response['sources'])
        )
        
        return jsonify({
            'success': True,
            'answer': rag_response['answer'],
            'sources': rag_response['sources'],
            'disclaimer': '⚠️ This guidance is for caregiving support only. Always consult healthcare professionals for medical diagnosis and treatment decisions.'
        }), 200
    
    except Exception as e:
        logger.error(f"Dementia query error: {e}")
        return jsonify({'error': 'Query failed'}), 500

@app.route('/dementia/query', methods=['POST'])
def dementia_query_noapi():
    return dementia_query()

@app.route('/api/dementia/history/<code_hash>', methods=['GET'])
def dementia_history(code_hash):
    """Get conversation history"""
    try:
        # Verify patient
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Invalid patient code'}), 404
        
        # Get conversations
        conversations = db_manager.get_conversations(code_hash)
        
        # Decrypt conversations
        decrypted_conversations = [{
            'id': conv['id'],
            'query': decrypt_data(conv['encrypted_query']),
            'response': decrypt_data(conv['encrypted_response']),
            'sources': conv['sources'],
            'createdAt': conv['created_at']
        } for conv in conversations]
        
        return jsonify({
            'success': True,
            'conversations': decrypted_conversations
        }), 200
    
    except Exception as e:
        logger.error(f"Get history error: {e}")
        return jsonify({'error': 'Failed to fetch history'}), 500

@app.route('/api/dementia/stats', methods=['GET'])
def dementia_stats():
    """Get RAG database statistics"""
    try:
        stats = db_manager.get_stats()
        return jsonify({
            'success': True,
            'research_papers': stats['total_papers'],
            'indexed_chunks': stats['total_chunks']
        }), 200
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return jsonify({'error': 'Stats unavailable'}), 500

# ==================== WEB PAGES ====================

@app.route("/", methods=["GET"])
def landing_page():
    """Serve landing page"""
    return render_template("landing.html")

@app.route("/index.html", methods=["GET"])
def index_page():
    """Serve index page"""
    return render_template("index.html")

@app.route("/privacy", methods=["GET"])
def privacy_page():
    """Serve index page"""
    return render_template("privacy.html")

@app.route('/.well-known/assetlinks.json')
def assetlinks():
    return send_from_directory('static/.well-known', 'assetlinks.json', mimetype='application/json')


# ==================== HEALTH CHECK ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'loveUAD API',
        'version': '1.0.0'
    }), 200

# ==================== ERROR HANDLERS ====================

# ==================== TWILIO VOICE CALL ROUTES ====================

@app.route('/api/twilio/call-medication', methods=['POST'])
def twilio_call_medication():
    """Trigger medication reminder call"""
    try:
        data = request.json
        code_hash = data.get('codeHash')
        phone_number = data.get('phoneNumber')
        medication_name = data.get('medicationName')
        dosage = data.get('dosage')
        time = data.get('scheduledTime')
        
        if not all([code_hash, phone_number, medication_name]):
            return jsonify({'error': 'Missing fields'}), 400
        
        # Verify patient exists
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Invalid patient'}), 404
        
        # Make the call
        call_sid = twilio_voice.make_medication_call(
            phone_number, medication_name, dosage, code_hash, time
        )
        
        return jsonify({'success': True, 'callSid': call_sid}), 200
        
    except Exception as e:
        logger.error(f"Twilio call error: {e}")
        return jsonify({'error': str(e)}), 500


# app.py - REPLACE the entire medication_twiml function (around line 1020)

# app.py - REPLACE medication_twiml function (around line 1020)

@app.route('/api/twilio/twiml/medication', methods=['GET', 'POST'])
def medication_twiml():
    from twilio.twiml.voice_response import VoiceResponse, Gather, Pause
    
    med_name = request.args.get('medication')
    code_hash = request.args.get('codeHash')
    time = request.args.get('time')
    call_type = request.args.get('call_type', 'reminder')
    retry_count = int(request.args.get('retry', 0))
    
    response = VoiceResponse()
    
    if call_type == 'reminder':
        response.say(
            f"<speak><prosody rate='slow'>Hello. This is your medication reminder. "
            f"<break time='1s'/> "
            f"It is time to take {med_name}. "
            f"<break time='1s'/> "
            f"Please take your medicine now. "
            f"<break time='1s'/> "
            f"I will call back in 10 minutes to check if you took it. "
            f"Goodbye.</prosody></speak>",
            voice='Polly.Joanna'
        )
        return str(response), 200, {'Content-Type': 'text/xml'}
    
    if call_type == 'followup':
        if request.method == 'POST' and request.form.get('SpeechResult'):
            speech_result = request.form.get('SpeechResult', '').lower()
            logger.info(f"📞 SPEECH: '{speech_result}' for {med_name}")
            
            yes_words = ['yes', 'yep', 'yeah', 'yah', 'correct', 'right', 'sure', 'okay', 'ok', 
                         'affirmative', 'absolutely', 'indeed', 'definitely', 'certainly', 
                         'i did', 'i have', 'taken', 'done', 'finished', 'took']
            
            if any(word in speech_result for word in yes_words):
                try:
                    with db_manager.get_connection() as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT encrypted_data FROM patients WHERE code_hash = %s", (code_hash,))
                        patient = cur.fetchone()
                        
                        if patient:
                            patient_data = decrypt_data(patient['encrypted_data'])
                            adherence = patient_data.get('medicationAdherence', [])
                            
                            # ✅ FIX: Match exact medication name format
                            adherence.append({
                                'medication': med_name,  # Use exact name from alarm
                                'scheduledTime': time,
                                'takenAt': datetime.now(timezone.utc).isoformat(),
                                'date': datetime.now().strftime('%Y-%m-%d'),
                                'status': 'taken',
                                'method': 'phone_followup'
                            })
                            
                            patient_data['medicationAdherence'] = adherence[-270:]
                            encrypted = encrypt_data(patient_data)
                            cur.execute("UPDATE patients SET encrypted_data = %s WHERE code_hash = %s", (encrypted, code_hash))
                            
                            # ✅ UPDATE STATUS TO TAKEN
                            cur.execute("""
                                UPDATE medication_reminders 
                                SET daily_status = 'TAKEN'
                                WHERE code_hash = %s AND medication_name = %s
                            """, (code_hash, med_name))
                            
                            conn.commit()
                            
                            logger.info(f"✅ SAVED: {med_name} at {time}, status=TAKEN")
                            
                            response.say(
                                "<speak><prosody rate='slow'>Thank you. "
                                "<break time='1s'/> "
                                "Your medication has been marked as taken. "
                                "<break time='1s'/> "
                                "Have a nice day. Goodbye.</prosody></speak>",
                                voice='Polly.Joanna'
                            )
                except Exception as e:
                    logger.error(f"❌ Error: {e}", exc_info=True)
            
            elif any(word in speech_result.split() for word in ['no', 'nope', 'not', 'haven\'t', 'didn\'t', 'forgot']):
                response.say(
                    "<speak><prosody rate='slow'>Okay. "
                    "<break time='1s'/> "
                    "Please remember to take your medication. "
                    "Goodbye.</prosody></speak>",
                    voice='Polly.Joanna'
                )
            
            else:
                if retry_count < 2:
                    gather = Gather(
                        input='speech',
                        action=f'/api/twilio/twiml/medication?medication={med_name}&codeHash={code_hash}&time={time}&call_type=followup&retry={retry_count + 1}',
                        method='POST',
                        speech_timeout='auto',
                        timeout=10,
                        language='en-US'
                    )
                    gather.say(
                        "<speak><prosody rate='slow'>I'm sorry, I didn't understand. "
                        "<break time='1s'/> "
                        "Please say YES if you took your medicine. "
                        "<break time='2s'/> "
                        "Or say NO if you have not taken it yet. "
                        "<break time='3s'/> "
                        "</prosody></speak>",
                        voice='Polly.Joanna'
                    )
                    response.append(gather)
        
        else:
            gather = Gather(
                input='speech',
                action=f'/api/twilio/twiml/medication?medication={med_name}&codeHash={code_hash}&time={time}&call_type=followup&retry=0',
                method='POST',
                speech_timeout='auto',
                timeout=10,
                language='en-US'
            )
            gather.say(
                f"<speak><prosody rate='slow'>Hello. "
                f"<break time='1s'/> "
                f"Did you take your {med_name}? "
                f"<break time='2s'/> "
                f"Please say YES if you took it. "
                f"<break time='1s'/> "
                f"Or say NO if you have not taken it yet. "
                f"<break time='3s'/> "
                f"</prosody></speak>",
                voice='Polly.Joanna'
            )
            response.append(gather)
        
        return str(response), 200, {'Content-Type': 'text/xml'}


from pywebpush import webpush, WebPushException
from datetime import datetime, timedelta, timezone

@app.route('/api/alarms/check-and-call', methods=['GET', 'POST'])
def check_and_call_alarms():
    try:
        now = datetime.now()
        current_time = now.strftime('%H:%M')
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            # CHECK 1: Find FIRST CALL alarms (time column) - only PENDING status
            cur.execute("""
                SELECT id, code_hash, medication_name, time, phone_number
                FROM medication_reminders
                WHERE active = true
                AND TO_CHAR(time, 'HH24:MI') = %s
                AND phone_number IS NOT NULL
                AND phone_number != ''
                AND daily_status = 'PENDING'
            """, (current_time,))
            
            reminder_alarms = cur.fetchall()
            
            # CHECK 2: Find FOLLOWUP CALL alarms (followup_time column) - only REMINDED status
            cur.execute("""
                SELECT id, code_hash, medication_name, time, phone_number
                FROM medication_reminders
                WHERE active = true
                AND TO_CHAR(followup_time, 'HH24:MI') = %s
                AND phone_number IS NOT NULL
                AND phone_number != ''
                AND daily_status = 'REMINDED'
            """, (current_time,))
            
            followup_alarms = cur.fetchall()
            
            calls_made = 0
            
            # PROCESS FIRST CALLS (REMINDER)
            for alarm in reminder_alarms:
                alarm_id = alarm['id']
                phone = alarm['phone_number']
                med_name = alarm['medication_name']
                code_hash = alarm['code_hash']
                
                try:
                    from twilio.rest import Client
                    
                    account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
                    auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
                    twilio_phone = os.environ.get('TWILIO_PHONE_NUMBER')
                    
                    if account_sid and auth_token and twilio_phone:
                        client = Client(account_sid, auth_token)
                        
                        twiml_url = f"https://loveuad.com/api/twilio/twiml/medication?medication={med_name}&codeHash={code_hash}&time={current_time}&call_type=reminder"
                        
                        call = client.calls.create(
                            to=phone,
                            from_=twilio_phone,
                            url=twiml_url,
                            method='GET'
                        )
                        
                        logger.info(f"📞 REMINDER CALL: {call.sid} to {phone} for {med_name}")
                        
                        # ✅ SEND PUSH NOTIFICATION
                        try:
                            cur.execute("""
                                SELECT subscription_data FROM push_subscriptions 
                                WHERE code_hash = %s AND active = true
                            """, (code_hash,))
                            subs = cur.fetchall()
                            
                            for sub in subs:
                                subscription_info = json.loads(sub['subscription_data'])
                                webpush(
                                    subscription_info=subscription_info,
                                    data=json.dumps({
                                        'title': '💊 Medication Reminder',
                                        'body': f'{med_name} at {current_time}',
                                        'medicationName': med_name,
                                        'scheduledTime': current_time,
                                        'tag': f'{med_name}-{current_time}'
                                    }),
                                    vapid_private_key=os.environ.get('VAPID_PRIVATE_KEY'),
                                    vapid_claims={"sub": "mailto:admin@loveuad.com"}
                                )
                            logger.info(f"📱 PUSH SENT: {med_name}")
                        except Exception as push_error:
                            logger.warning(f"Push notification failed: {push_error}")
                        
                        calls_made += 1
                        
                        # ✅ UPDATE STATUS TO REMINDED
                        cur.execute("""
                            UPDATE medication_reminders 
                            SET last_called = %s,
                                daily_status = 'REMINDED'
                            WHERE id = %s
                        """, (now, alarm_id))
                        
                except Exception as call_error:
                    logger.error(f"Twilio reminder call failed: {call_error}")
            
            # PROCESS FOLLOWUP CALLS
            for alarm in followup_alarms:
                phone = alarm['phone_number']
                med_name = alarm['medication_name']
                code_hash = alarm['code_hash']
                alarm_id = alarm['id']
                
                try:
                    from twilio.rest import Client
                    
                    account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
                    auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
                    twilio_phone = os.environ.get('TWILIO_PHONE_NUMBER')
                    
                    if account_sid and auth_token and twilio_phone:
                        client = Client(account_sid, auth_token)
                        
                        twiml_url = f"https://loveuad.com/api/twilio/twiml/medication?medication={med_name}&codeHash={code_hash}&time={current_time}&call_type=followup"
                        
                        call = client.calls.create(
                            to=phone,
                            from_=twilio_phone,
                            url=twiml_url,
                            method='GET'
                        )
                        
                        logger.info(f"📞 FOLLOWUP CALL: {call.sid} to {phone} for {med_name}")
                        calls_made += 1
                        
                        # ✅ UPDATE STATUS TO FOLLOWUP
                        cur.execute("""
                            UPDATE medication_reminders 
                            SET daily_status = 'FOLLOWUP'
                            WHERE id = %s
                        """, (alarm_id,))
                        
                except Exception as call_error:
                    logger.error(f"Twilio followup call failed: {call_error}")
            
            conn.commit()
            
            logger.info(f"✓ Checked at {current_time}, made {calls_made} calls ({len(reminder_alarms)} reminders, {len(followup_alarms)} followups)")
            return jsonify({
                'success': True, 
                'calls_made': calls_made,
                'reminder_calls': len(reminder_alarms),
                'followup_calls': len(followup_alarms),
                'time_checked': current_time
            }), 200
            
    except Exception as e:
        logger.error(f"Alarm check error: {e}")
        return jsonify({'error': str(e)}), 500





@app.route('/api/twilio/webhook/status', methods=['POST'])
def twilio_webhook_status():
    """Handle call status updates"""
    call_sid = request.form.get('CallSid')
    call_status = request.form.get('CallStatus')
    
    logger.info(f"Call {call_sid} status: {call_status}")
    
    # You can log this to database if needed
    return '', 200

# ==================== END TWILIO ROUTES ====================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# EXACT FIX FOR app.py
# Add this code RIGHT BEFORE the line: if __name__ == '__main__':

# ==================== DUPLICATE ROUTES WITHOUT /api/ PREFIX ====================
# These allow both mobile and web apps to work



@app.route('/patient/login', methods=['POST'])
def login_patient_noapi():
    return login_patient()

@app.route('/patient/qr/<code>', methods=['GET'])
def generate_qr_noapi(code):
    return generate_qr(code)

@app.route('/medications/add', methods=['POST'])
def add_medication_noapi():
    return add_medication()

@app.route('/medications/<code_hash>', methods=['GET'])
def get_medications_noapi(code_hash):
    return get_medications(code_hash)

@app.route('/medications/update', methods=['POST'])
def update_medication_noapi():
    return update_medication()



@app.route('/api/medications/schedule', methods=['POST'])
@app.route('/medications/schedule', methods=['POST'])
def schedule_medications_noapi():
    data = request.json
    code_hash = data.get('codeHash')
    medications = data.get('medications')
    
    if not code_hash or not medications:
        return jsonify({'error': 'Missing required fields'}), 400
    
    patient = db_manager.get_patient_data(code_hash)
    if not patient:
        return jsonify({'error': 'Invalid patient code'}), 404
    
    # GET PHONE NUMBER FROM PATIENT DATA
    patient_data = decrypt_data(patient['encrypted_data'])
    phone_number = patient_data.get('phoneNumber', '')
    
    with db_manager.get_connection() as conn:
        cur = conn.cursor()
        
        # ✅ Save medications using encrypted_data column
        for med in medications:
            med['createdAt'] = datetime.utcnow().isoformat()
            encrypted_data = encrypt_data(med)
            
            cur.execute("""
                INSERT INTO medications (code_hash, encrypted_data, active)
                VALUES (%s, %s, true)
            """, (code_hash, encrypted_data))
            logger.info(f"✓ Medication saved: {med['name']}")
        
        # ✅ Save alarms to medication_reminders
        for med in medications:
            for time in med.get('times', []):
                time_obj = datetime.strptime(time, '%H:%M')
                followup_obj = time_obj + timedelta(minutes=10)
                followup_time = followup_obj.strftime('%H:%M')
                
                cur.execute("""
                    INSERT INTO medication_reminders (code_hash, medication_name, time, followup_time, phone_number, active, daily_status)
                    VALUES (%s, %s, %s, %s, %s, true, 'PENDING')
                    ON CONFLICT DO NOTHING
                """, (code_hash, med['name'], time, followup_time, phone_number))
                logger.info(f"✓ Alarm created: {med['name']} at {time}, followup at {followup_time}")
        
        conn.commit()
    
    return jsonify({'success': True}), 200

@app.route('/scan/prescription', methods=['POST'])
def scan_prescription_noapi():
    return scan_prescription()

# app.py - Add push notification endpoint

from pywebpush import webpush, WebPushException

@app.route('/api/alarms/trigger-push', methods=['POST'])
def trigger_push_alarm():
    try:
        data = request.json
        code_hash = data.get('codeHash')
        medication_name = data.get('medicationName')
        time = data.get('time')
        
        # Get user's push subscription
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT subscription_data FROM push_subscriptions 
                WHERE code_hash = %s AND active = true
            """, (code_hash,))
            subs = cur.fetchall()
            
            for sub in subs:
                subscription_info = json.loads(sub['subscription_data'])
                
                webpush(
                    subscription_info=subscription_info,
                    data=json.dumps({
                        'title': '💊 Medication Reminder',
                        'body': f'{medication_name} - {time}',
                        'icon': '/static/icon-192x192.png',
                        'badge': '/static/badge-72x72.png',
                        'vibrate': [500, 200, 500, 200, 500],
                        'requireInteraction': True,
                        'tag': f'{medication_name}-{time}'
                    }),
                    vapid_private_key=os.environ.get('VAPID_PRIVATE_KEY'),
                    vapid_claims={
                        "sub": "mailto:kanchan.g12@loveuad.com"
                    }
                )
        
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f'Push notification error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/health/records/<code_hash>', methods=['GET'])
def get_health_records_noapi(code_hash):
    return get_health_records(code_hash)

@app.route('/api/health/record', methods=['POST'])
@app.route('/health/record', methods=['POST'])
def add_health_record_noapi():
    try:
        data = request.json
        code_hash = data.get('codeHash')
        record_type = data.get('recordType')
        record_date = data.get('recordDate')
        
        if not code_hash or not record_type:
            return jsonify({'error': 'Missing fields'}), 400
        
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Invalid code'}), 404
        
        metadata = {
            'recordType': record_type,
            'ocrText': data.get('ocrText', ''),
            'extractedData': data.get('extractedData', {}),
            'aiInsights': data.get('aiInsights', {}),
            'notes': data.get('notes', ''),
            'imageId': data.get('imageId', ''),
            'createdAt': datetime.utcnow().isoformat()
        }
        
        encrypted_metadata = encrypt_data(metadata)
        db_manager.insert_health_record(code_hash, 'ai_analysis', encrypted_metadata, record_date)
        
        return jsonify({'success': True}), 201
    except Exception as e:
        logger.error(f"Record error: {e}")
        return jsonify({'error': 'Failed'}), 500


        

@app.route('/api/health/ocr', methods=['POST'])
def process_ocr_api():
    return process_ocr_noapi()

@app.route('/health/ocr', methods=['POST'])
def process_ocr_noapi():
    try:
        # Check if Gemini Vision is available
        if not vision_model:
            return jsonify({
                'error': 'Vision API not configured',
                'details': 'GEMINI_API_KEY environment variable is not set. Please configure it to enable OCR.'
            }), 503
        
        data = request.json
        image_data = data.get('imageData')
        patient_age = data.get('patientAge')
        patient_gender = data.get('patientGender')
        
        if not image_data:
            return jsonify({'error': 'Missing image'}), 400
        
        # Decode base64 image
        try:
            image_bytes = base64.b64decode(image_data.split(',')[1] if ',' in image_data else image_data)
            image = Image.open(io.BytesIO(image_bytes))
        except Exception as e:
            logger.error(f"Image decode error: {e}")
            return jsonify({'error': 'Invalid image data'}), 400
        
        # OCR with Gemini Vision - IMPROVED PROMPT
        prompt = """You are a medical prescription reader. Extract ALL medications from this image.

Look for:
- Drug names (in ANY font size or style - bold, regular, handwritten)
- Dosages (mg, ml, tablets, etc.)
- Frequency (how many times per day)
- Any instructions

CRITICAL: Extract EVERY medication you see, even if formatting is unclear.

Return in this EXACT format for EACH medication:
MEDICATION: [full drug name]
DOSAGE: [amount and unit]
FREQUENCY: [times per day - use number only like 1, 2, 3]
INSTRUCTIONS: [any special instructions or "As directed"]

Example:
MEDICATION: Aspirin
DOSAGE: 100mg
FREQUENCY: 1
INSTRUCTIONS: Take with food

Extract all medications now:"""
        
        try:
            response = vision_model.generate_content([prompt, image])
            ocr_text = response.text
            logger.info(f"OCR Raw Response: {ocr_text}")
        except Exception as e:
            logger.error(f"Gemini Vision API error: {e}")
            return jsonify({
                'error': 'OCR processing failed',
                'details': 'Vision API error - Check Gemini API key and quota'
            }), 500
        
        filtered_text = pii_filter.remove_pii(ocr_text)
        
        # IMPROVED PARSING - more flexible
        medications = []
        lines = filtered_text.split('\n')
        current_med = {}
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # More flexible keyword matching
            line_upper = line.upper()
            
            if 'MEDICATION:' in line_upper or 'DRUG:' in line_upper or 'MEDICINE:' in line_upper:
                if current_med and 'name' in current_med:
                    medications.append(current_med)
                # Extract name after colon
                name = line.split(':', 1)[1].strip() if ':' in line else line
                current_med = {'name': name}
                
            elif ('DOSAGE:' in line_upper or 'DOSE:' in line_upper) and current_med:
                dosage = line.split(':', 1)[1].strip() if ':' in line else line
                current_med['dosage'] = dosage
                
            elif ('FREQUENCY:' in line_upper or 'TIMES:' in line_upper or 'FREQ:' in line_upper) and current_med:
                freq_text = line.split(':', 1)[1].strip() if ':' in line else line
                # Extract number from text
                import re
                numbers = re.findall(r'\d+', freq_text)
                if numbers:
                    current_med['frequency'] = int(numbers[0])
                elif 'once' in freq_text.lower():
                    current_med['frequency'] = 1
                elif 'twice' in freq_text.lower():
                    current_med['frequency'] = 2
                elif 'three' in freq_text.lower() or 'thrice' in freq_text.lower():
                    current_med['frequency'] = 3
                else:
                    current_med['frequency'] = 1
                    
            elif ('INSTRUCTIONS:' in line_upper or 'INSTRUCTION:' in line_upper or 'NOTES:' in line_upper) and current_med:
                instructions = line.split(':', 1)[1].strip() if ':' in line else line
                current_med['instructions'] = instructions
        
        # Add last medication
        if current_med and 'name' in current_med:
            medications.append(current_med)
        
        # If no medications found with structured format, try to extract from free text
        if not medications:
            logger.warning("No structured medications found, attempting free-text extraction")
            # Ask Gemini to be more aggressive
            retry_prompt = f"""The previous extraction failed. This is a prescription image.

Your task: Find EVERY medication name visible in the image.

Original text extracted:
{ocr_text}

Return ONLY a simple list:
1. [Medication name] - [dosage if visible]
2. [Medication name] - [dosage if visible]

Be aggressive - extract anything that looks like a drug name."""
            
            try:
                retry_response = vision_model.generate_content([retry_prompt, image])
                retry_text = retry_response.text
                logger.info(f"Retry extraction: {retry_text}")
                
                # Parse numbered list
                import re
                for line in retry_text.split('\n'):
                    if line.strip() and any(c.isalpha() for c in line):
                        # Remove numbering
                        clean_line = re.sub(r'^\d+[\.\)]\s*', '', line.strip())
                        if '-' in clean_line:
                            parts = clean_line.split('-', 1)
                            medications.append({
                                'name': parts[0].strip(),
                                'dosage': parts[1].strip() if len(parts) > 1 else 'As directed',
                                'frequency': 1,
                                'instructions': 'As directed'
                            })
                        elif clean_line:
                            medications.append({
                                'name': clean_line,
                                'dosage': 'As directed',
                                'frequency': 1,
                                'instructions': 'As directed'
                            })
            except Exception as retry_error:
                logger.error(f"Retry extraction failed: {retry_error}")
        
        for med in medications:
            freq = med.get('frequency', 1)
            if freq == 1:
                med['times'] = ['09:00']
            elif freq == 2:
                med['times'] = ['09:00', '21:00']
            elif freq == 3:
                med['times'] = ['09:00', '14:00', '21:00']
            else:
                med['times'] = ['09:00', '13:00', '17:00', '21:00']
        
        # EXTRACT APPOINTMENT DATES from the scanned document
        appointment_info = None
        try:
            appointment_prompt = """Look at this medical document and extract ANY appointment or follow-up date mentioned.

Search for phrases like:
- "Next appointment"
- "Follow up"
- "Review date"
- "See you on"
- "Appointment on"
- Any date mentioned for future visits

If you find an appointment date, return ONLY:
APPOINTMENT_DATE: [DD/MM/YYYY or MM/DD/YYYY format]
APPOINTMENT_TYPE: [brief description like "Follow-up", "Review", "Consultation"]

If NO appointment date is found, return:
NO_APPOINTMENT_FOUND

Scan the document now:"""
            
            appointment_response = vision_model.generate_content([appointment_prompt, image])
            appointment_text = appointment_response.text.strip()
            logger.info(f"Appointment extraction: {appointment_text}")
            
            if 'NO_APPOINTMENT_FOUND' not in appointment_text:
                # Parse the appointment
                import re
                from dateutil import parser
                
                date_match = re.search(r'APPOINTMENT_DATE:\s*(.+)', appointment_text)
                type_match = re.search(r'APPOINTMENT_TYPE:\s*(.+)', appointment_text)
                
                if date_match:
                    date_str = date_match.group(1).strip()
                    try:
                        # Try to parse the date
                        appointment_date = parser.parse(date_str, dayfirst=True)
                        appointment_info = {
                            'date': appointment_date.strftime('%Y-%m-%d'),
                            'type': type_match.group(1).strip() if type_match else 'Appointment',
                            'found': True
                        }
                        logger.info(f"Appointment found: {appointment_info}")
                    except Exception as parse_error:
                        logger.warning(f"Could not parse appointment date: {date_str} - {parse_error}")
        except Exception as appt_error:
            logger.warning(f"Appointment extraction failed: {appt_error}")
            # Continue even if appointment extraction fails
        
        ai_insights = {'enabled': False}
        try:
            # NO DIAGNOSIS VERSION
            analysis_prompt = f"""Provide CAREGIVING GUIDANCE for these medications prescribed to a {patient_age} year old {patient_gender}.

CRITICAL RULES:
- DO NOT diagnose why these were prescribed
- DO NOT interpret the patient's condition
- ONLY provide general medication information and caregiving tips

Medications:
{filtered_text}

Provide ONLY:
1. Brief summary (general use of these medications - not patient-specific diagnosis)
2. Important safety considerations
3. Common side effects healthcare professionals mention
4. Potential interactions to discuss with doctor
5. Practical caregiving tips for medication management

Always remind: "Discuss all questions with the prescribing healthcare provider."

Be concise and focus on practical caregiving support."""
            
            analysis_response = vision_model.generate_content(analysis_prompt)
            ai_insights = {
                'enabled': True,
                'analysis': analysis_response.text,
                'model': 'gemini-1.5-flash',
                'age_group': f'{patient_age} years old',
                'personalized': True,
                'disclaimer': '⚠️ This is caregiving guidance only, NOT medical diagnosis. Consult healthcare providers for all medical decisions.'
            }
        except Exception as e:
            logger.error(f"AI analysis error: {e}")
            # Continue even if AI analysis fails - medications are already extracted
            ai_insights = {
                'enabled': False,
                'error': 'AI analysis unavailable'
            }
        # SAVE OCR DATA TO DATABASE
        try:
            code_hash = data.get('codeHash')
            if code_hash:
                for med in medications:
                    med['createdAt'] = datetime.utcnow().isoformat()
                    encrypted_data = encrypt_data(med)
                    db_manager.insert_medication(code_hash, encrypted_data)
                
                record_metadata = {
                    'ocrText': filtered_text,
                    'medications': medications,
                    'appointment': appointment_info,
                    'scannedAt': datetime.utcnow().isoformat()
                }
                encrypted_metadata = encrypt_data(record_metadata)
                db_manager.insert_health_record(code_hash, 'ai_analysis', encrypted_metadata, None)
                
                logger.info(f"✓ OCR saved {len(medications)} meds")
        except Exception as e:
            logger.error(f"OCR save error: {e}")
        
        
        return jsonify({
            'success': True,
            'ocrResult': {
                'raw_text': filtered_text,
                'extracted_data': {
                    'medications': medications,
                    'appointment': appointment_info
                },
                'ai_insights': ai_insights
            }
        }), 200
    except Exception as e:
        logger.error(f"OCR error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/alarms/deactivate-all', methods=['POST'])
def deactivate_all_alarms():
    """Deactivate all alarms for a patient"""
    try:
        data = request.json
        code_hash = data.get('codeHash')
        
        if not code_hash:
            return jsonify({'success': False, 'error': 'Missing codeHash'}), 400
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            cur.execute("""
                UPDATE medication_reminders 
                SET active = true
                WHERE code_hash = %s
            """, (code_hash,))
            
            affected_rows = cur.rowcount
            conn.commit()
        
        logger.info(f'✅ Deactivated {affected_rows} alarms for patient: {code_hash[:8]}...')
        
        return jsonify({
            'success': True,
            'message': f'{affected_rows} alarms deactivated',
            'alarms_stopped': affected_rows
        })
        
    except Exception as e:
        logger.error(f'Alarm deactivation error: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/medications/delete', methods=['POST'])
def delete_medication():
    """Delete medication and its alarms from database"""
    try:
        data = request.json
        code_hash = data.get('codeHash')
        medication_name = data.get('medicationName')
        
        if not code_hash or not medication_name:
            return jsonify({'success': False, 'error': 'Missing data'}), 400
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            # STEP 1: Delete all alarms for this medication
            cur.execute("""
                DELETE FROM medication_reminders 
                WHERE code_hash = %s AND medication_name = %s
            """, (code_hash, medication_name))
            
            alarms_deleted = cur.rowcount
            
            # STEP 2: Delete medication from medications table
            cur.execute("""
                DELETE FROM medications 
                WHERE code_hash = %s
            """, (code_hash,))
            
            meds_deleted = cur.rowcount
            
            conn.commit()
        
        logger.info(f'✅ Deleted medication: {medication_name} ({meds_deleted} meds, {alarms_deleted} alarms)')
        
        return jsonify({
            'success': True,
            'message': f'Deleted {medication_name}',
            'alarms_deleted': alarms_deleted,
            'medications_deleted': meds_deleted
        })
        
    except Exception as e:
        logger.error(f'Delete medication error: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/health/medication-taken', methods=['POST'])
def record_medication_taken():
    """Record when a patient takes their medication"""
    try:
        data = request.json
        code_hash = data.get('codeHash')
        medication_name = data.get('medicationName')
        time = data.get('scheduledTime')
        taken_at = data.get('takenAt')
        
        if not all([code_hash, medication_name, time, taken_at]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Store in health records
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Patient not found'}), 404
        
        adherence_record = {
            'medication': medication_name,
            'scheduledTime': time,
            'takenAt': taken_at,
            'date': datetime.fromisoformat(taken_at.replace('Z', '+00:00')).strftime('%Y-%m-%d'),
            'status': 'taken'
        }
        
        # Get existing medication adherence records
        patient_data = decrypt_data(patient['encrypted_data'])
        adherence_history = patient_data.get('medicationAdherence', [])
        adherence_history.append(adherence_record)
        
        # Keep only last 90 days
        patient_data['medicationAdherence'] = adherence_history[-270:]  # 3 meds * 3 times * 30 days
        
        # Save back to database
        encrypted_data = encrypt_data(patient_data)
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE patients SET encrypted_data = %s WHERE code_hash = %s",
                (encrypted_data, code_hash)
            )
            conn.commit()
        
        logger.info(f"Medication adherence recorded for patient {code_hash[:8]}...")
        return jsonify({'success': True}), 200
        
    except Exception as e:
        logger.error(f"Medication adherence tracking error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health/medication-adherence/<code_hash>', methods=['GET'])
def get_medication_adherence(code_hash):
    """Get medication adherence history for a patient"""
    try:
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Patient not found'}), 404
        
        patient_data = decrypt_data(patient['encrypted_data'])
        adherence_history = patient_data.get('medicationAdherence', [])
        
        # Calculate adherence statistics
        today = datetime.now().strftime('%Y-%m-%d')
        last_7_days = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
        
        recent_records = [r for r in adherence_history if r['date'] in last_7_days]
        
        stats = {
            'totalRecords': len(adherence_history),
            'last7Days': len(recent_records),
            'todayRecords': len([r for r in adherence_history if r['date'] == today]),
            'history': adherence_history[-50:]  # Last 50 records
        }
        
        return jsonify({'success': True, 'adherence': stats}), 200
        
    except Exception as e:
        logger.error(f"Get adherence error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health/appointments/add', methods=['POST'])
def add_appointment():
    """Add an appointment for a patient"""
    try:
        data = request.json
        code_hash = data.get('codeHash')
        appointment = data.get('appointment')
        
        if not all([code_hash, appointment]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Patient not found'}), 404
        
        patient_data = decrypt_data(patient['encrypted_data'])
        appointments = patient_data.get('appointments', [])
        
        # Add new appointment
        appointment['id'] = 'appt-' + str(int(datetime.now().timestamp() * 1000))
        appointment['createdAt'] = datetime.now().isoformat()
        appointments.append(appointment)
        
        patient_data['appointments'] = appointments
        
        # Save to database
        encrypted_data = encrypt_data(patient_data)
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE patients SET encrypted_data = %s WHERE code_hash = %s",
                (encrypted_data, code_hash)
            )
            conn.commit()
        
        logger.info(f"Appointment added for patient {code_hash[:8]}...")
        return jsonify({'success': True, 'appointment': appointment}), 200
        
    except Exception as e:
        logger.error(f"Add appointment error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health/appointments/<code_hash>', methods=['GET'])
def get_appointments(code_hash):
    """Get all appointments for a patient"""
    try:
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Patient not found'}), 404
        
        patient_data = decrypt_data(patient['encrypted_data'])
        appointments = patient_data.get('appointments', [])
        
        return jsonify({'success': True, 'appointments': appointments}), 200
        
    except Exception as e:
        logger.error(f"Get appointments error: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== FEATURE 1: ANONYMOUS MONTHLY CAREGIVER BURDEN SURVEY ====================

@app.route('/api/survey/check-eligibility/<code_hash>', methods=['GET'])
def check_survey_eligibility(code_hash):
    """
    Check if the caregiver is eligible for a survey (Day 30, 60, 90, etc.)
    Returns survey day if eligible, None if not
    """
    try:
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Patient not found'}), 404
        
        # Calculate account age in days
        created_at = patient.get('created_at')
        if not created_at:
            return jsonify({'eligible': False}), 200
        
        account_age_days = (datetime.now() - created_at).days
        
        # Check if account is at a 30-day milestone
        if account_age_days < 30:
            return jsonify({'eligible': False, 'accountAgeDays': account_age_days}), 200
        
        # Calculate which survey milestone (30, 60, 90, 120, etc.)
        survey_day = (account_age_days // 30) * 30
        
        # Check if survey already completed for this milestone
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM survey_responses WHERE code_hash = %s AND survey_day = %s",
                (code_hash, survey_day)
            )
            existing_survey = cur.fetchone()
        
        if existing_survey:
            return jsonify({'eligible': False, 'accountAgeDays': account_age_days, 'reason': 'Already completed'}), 200
        
        # Generate secure survey URL with encrypted code parameter
        survey_url = f"https://tally.so/r/wgEAQB?code={code_hash[:8]}&day={survey_day}"
        
        return jsonify({
            'eligible': True,
            'surveyDay': survey_day,
            'accountAgeDays': account_age_days,
            'surveyUrl': survey_url
        }), 200
        
    except Exception as e:
        logger.error(f"Survey eligibility check error: {e}")
        return jsonify({'error': str(e)}), 500

# app.py - Add endpoint (around line 1800)

@app.route('/api/account/request-deletion', methods=['POST'])
def request_account_deletion():
    """Record account deletion request"""
    try:
        data = request.json
        code_hash = data.get('codeHash')
        patient_code = data.get('patientCode')
        requested_at = data.get('requestedAt')
        
        if not code_hash or not patient_code:
            return jsonify({'error': 'Missing required fields'}), 400
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS deletion_requests (
                    id SERIAL PRIMARY KEY,
                    code_hash VARCHAR(64) NOT NULL,
                    patient_code VARCHAR(21) NOT NULL,
                    requested_at TIMESTAMP NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(code_hash)
                )
            """)
            
            cur.execute("""
                INSERT INTO deletion_requests (code_hash, patient_code, requested_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (code_hash) DO NOTHING
            """, (code_hash, patient_code, requested_at))
            
            conn.commit()
        
        # Send admin notification
        try:
            import smtplib
            from email.mime.text import MIMEText
            
            msg = MIMEText(f"Deletion Request\n\nCode: {patient_code}\nHash: {code_hash}\nTime: {requested_at}")
            msg['Subject'] = f'Account Deletion - {patient_code}'
            msg['From'] = 'kanchanloveuad@gmail.com'
            msg['To'] = 'kanchan.g12@loveuad.com'
            
            smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
            smtp_port = int(os.environ.get('SMTP_PORT', '587'))
            
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(os.environ.get('SMTP_USER'), os.environ.get('SMTP_PASS'))
                server.send_message(msg)
        except:
            pass
        
        logger.info(f"✓ Deletion request: {patient_code}")
        return jsonify({'success': True}), 200
        
    except Exception as e:
        logger.error(f"Deletion request error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/survey/record-completion', methods=['POST'])
def record_survey_completion():
    """
    Record survey completion - ONLY stores code_hash, date, result bucket
    NO PII, NO text answers
    """
    try:
        data = request.json
        code_hash = data.get('codeHash')
        survey_day = data.get('surveyDay')
        result_bucket = data.get('resultBucket')  # 'Low', 'Medium', 'High'
        
        if not all([code_hash, survey_day, result_bucket]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        if result_bucket not in ['Low', 'Medium', 'High']:
            return jsonify({'error': 'Invalid result bucket'}), 400
        
        # Store ONLY anonymous data
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO survey_responses (code_hash, completion_date, result_bucket, survey_day)
                VALUES (%s, CURRENT_DATE, %s, %s)
                ON CONFLICT (code_hash, survey_day) DO NOTHING
            """, (code_hash, result_bucket, survey_day))
            conn.commit()
        
        logger.info(f"Survey recorded: Day {survey_day}, Bucket: {result_bucket}")
        return jsonify({'success': True}), 200
        
    except Exception as e:
        logger.error(f"Survey recording error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/survey/aggregate-stats', methods=['GET'])
def get_survey_aggregate_stats():
    """
    Get aggregated survey statistics - NO individual data
    Returns mean reduction in burden scores
    """
    try:
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            # Get aggregated stats by bucket and survey day
            cur.execute("""
                SELECT 
                    survey_day,
                    result_bucket,
                    COUNT(*) as count
                FROM survey_responses
                GROUP BY survey_day, result_bucket
                ORDER BY survey_day, result_bucket
            """)
            results = cur.fetchall()
        
        stats = {
            'totalResponses': sum(r['count'] for r in results),
            'byDay': {},
            'byBucket': {'Low': 0, 'Medium': 0, 'High': 0}
        }
        
        for row in results:
            day = f"Day {row['survey_day']}"
            if day not in stats['byDay']:
                stats['byDay'][day] = {'Low': 0, 'Medium': 0, 'High': 0}
            stats['byDay'][day][row['result_bucket']] = row['count']
            stats['byBucket'][row['result_bucket']] += row['count']
        
        return jsonify({'success': True, 'stats': stats}), 200
        
    except Exception as e:
        logger.error(f"Survey stats error: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== FEATURE 2: CUMULATIVE DAILY ACTIVE USER (DAU) TRACKING ====================

@app.route('/api/analytics/app-launch', methods=['POST'])
def record_app_launch():
    """
    Record app launch event - implements STRICT anonymization
    1. Check if code launched today (using temporary tracker)
    2. If unique launch, increment aggregated hourly count
    3. DISCARD the code immediately - only keep aggregated count
    """
    try:
        data = request.json
        code_hash = data.get('codeHash')
        
        if not code_hash:
            return jsonify({'error': 'Missing code'}), 400
        
        now = datetime.now()
        today = now.date()
        current_hour = now.hour
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            # Check if this code already launched today
            cur.execute("""
                SELECT 1 FROM daily_launch_tracker 
                WHERE code_hash = %s AND launch_date = %s
            """, (code_hash, today))
            already_launched_today = cur.fetchone()
            
            if already_launched_today:
                # Already counted for today - no action needed
                return jsonify({'success': True, 'counted': False}), 200
            
            # This is a UNIQUE daily launch - add to tracker
            cur.execute("""
                INSERT INTO daily_launch_tracker (code_hash, launch_date)
                VALUES (%s, %s)
                ON CONFLICT (code_hash, launch_date) DO NOTHING
            """, (code_hash, today))
            
            # Increment the AGGREGATED hourly count (NO code stored here)
            cur.execute("""
                INSERT INTO daily_active_users (event_date, event_hour, launch_count)
                VALUES (%s, %s, 1)
                ON CONFLICT (event_date, event_hour) 
                DO UPDATE SET launch_count = daily_active_users.launch_count + 1
            """, (today, current_hour))
            
            # CRITICAL: Clean up old tracker data (keep only last 2 days)
            cur.execute("""
                DELETE FROM daily_launch_tracker 
                WHERE launch_date < %s
            """, (today - timedelta(days=2),))
            
            conn.commit()
        
        logger.info(f"DAU recorded: {today} {current_hour}:00 (Aggregated count incremented)")
        return jsonify({'success': True, 'counted': True}), 200
        
    except Exception as e:
        logger.error(f"App launch tracking error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/dau-stats', methods=['GET'])
def get_dau_stats():
    """
    Get aggregated DAU statistics
    PUBLIC WORDING COMPLIANT: "Cumulative Daily Active Users are tracked by counting 
    the total number of unique, daily 'App Launch' events generated by anonymous codes. 
    We do not track the identity of the user."
    """
    try:
        days = request.args.get('days', 30, type=int)
        start_date = datetime.now().date() - timedelta(days=days)
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            # Get daily totals
            cur.execute("""
                SELECT 
                    event_date,
                    SUM(launch_count) as daily_total
                FROM daily_active_users
                WHERE event_date >= %s
                GROUP BY event_date
                ORDER BY event_date DESC
            """, (start_date,))
            daily_stats = cur.fetchall()
            
            # Get hourly distribution (last 7 days)
            cur.execute("""
                SELECT 
                    event_hour,
                    AVG(launch_count) as avg_launches
                FROM daily_active_users
                WHERE event_date >= %s
                GROUP BY event_hour
                ORDER BY event_hour
            """, (datetime.now().date() - timedelta(days=7),))
            hourly_stats = cur.fetchall()
        
        stats = {
            'disclaimer': 'Cumulative Daily Active Users are tracked by counting the total number of unique, daily App Launch events generated by anonymous codes. We do not track the identity of the user.',
            'dailyTotals': [{'date': str(row['event_date']), 'count': row['daily_total']} for row in daily_stats],
            'hourlyAverage': [{'hour': row['event_hour'], 'avgCount': float(row['avg_launches'])} for row in hourly_stats],
            'totalDaysTracked': len(daily_stats)
        }
        
        return jsonify({'success': True, 'stats': stats}), 200
        
    except Exception as e:
        logger.error(f"DAU stats error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/caregiver/connect', methods=['POST'])
def connect_caregiver_noapi():
    return connect_caregiver()



@app.route('/dementia/history/<code_hash>', methods=['GET'])
def dementia_history_noapi(code_hash):
    return dementia_history(code_hash)

@app.route('/dementia/stats', methods=['GET'])
def dementia_stats_noapi():
    return dementia_stats()

@app.route('/patient/update-tier', methods=['POST'])
def update_patient_tier_noapi():
    try:
        data = request.json
        patient_code = data.get('patientCode')
        tier = data.get('tier')
        
        if not patient_code or tier not in ['free', 'premium']:
            return jsonify({'error': 'Invalid request'}), 400
        
        code_hash = hash_patient_code(patient_code)
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Invalid code'}), 404
        
        patient_data = decrypt_data(patient['encrypted_data'])
        patient_data['tier'] = tier
        patient_data['tierUpdatedAt'] = datetime.utcnow().isoformat()
        encrypted_data = encrypt_data(patient_data)
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE patients SET encrypted_data = %s WHERE code_hash = %s;", 
                       (encrypted_data, code_hash))
            conn.commit()
        
        return jsonify({'success': True, 'tier': tier}), 200
    except Exception as e:
        logger.error(f"Tier update error: {e}")
        return jsonify({'error': 'Failed'}), 500

# ==================== ADMIN PANEL - PASSWORD PROTECTED ====================

@app.route('/api/admin/check-tables', methods=['GET'])
def check_analytics_tables():
    """Debug endpoint to check if analytics tables exist and have data"""
    try:
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            tables_status = {}
            
            # Check each table
            for table in ['patients', 'caregivers', 'medications', 'survey_responses', 'daily_active_users', 'daily_launch_tracker']:
                try:
                    cur.execute(f"SELECT COUNT(*) as count FROM {table}")
                    count = cur.fetchone()['count']
                    tables_status[table] = {'exists': True, 'count': count}
                except Exception as e:
                    tables_status[table] = {'exists': False, 'error': str(e)}
            
            return jsonify({'success': True, 'tables': tables_status}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/analytics', methods=['GET'])
def admin_analytics_page():
    """
    Password-protected admin panel to view aggregated analytics
    Access: https://loveuad.com/admin/analytics
    """
    return render_template('admin_analytics.html')

@app.route('/api/admin/verify-password', methods=['POST'])
def verify_admin_password():
    """Verify admin password - stored in environment variable for security"""
    try:
        data = request.json
        password = data.get('password')
        
        # Admin password from environment variable (set in Cloud Run)
        admin_password = os.environ.get('ADMIN_PASSWORD', 'LoveUAD2025!Admin')
        
        if password == admin_password:
            return jsonify({'success': True, 'token': 'authenticated'}), 200
        else:
            return jsonify({'success': False, 'error': 'Invalid password'}), 401
            
    except Exception as e:
        logger.error(f"Admin auth error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/dashboard-stats', methods=['GET'])
def get_admin_dashboard_stats():
    """
    Get comprehensive dashboard statistics for admin panel
    Shows: Total users, Active users (logged in last 7 days), Survey stats, DAU
    """
    try:
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            # Total patient accounts
            cur.execute("SELECT COUNT(*) as count FROM patients")
            total_patients = cur.fetchone()['count']
            
            # Total caregiver accounts
            cur.execute("SELECT COUNT(*) as count FROM caregivers")
            total_caregivers = cur.fetchone()['count']
            
            # Active users (logged in last 7 days) - from daily_launch_tracker
            cur.execute("""
                SELECT COUNT(DISTINCT code_hash) as count 
                FROM daily_launch_tracker 
                WHERE launch_date >= CURRENT_DATE - INTERVAL '7 days'
            """)
            active_last_7_days = cur.fetchone()
            active_users = active_last_7_days['count'] if active_last_7_days else 0
            
            # Survey statistics
            cur.execute("""
                SELECT 
                    COUNT(DISTINCT code_hash) as unique_respondents,
                    COUNT(*) as total_responses,
                    survey_day,
                    result_bucket,
                    COUNT(*) as count
                FROM survey_responses
                GROUP BY survey_day, result_bucket
                ORDER BY survey_day, result_bucket
            """)
            survey_data = cur.fetchall()
            
            # DAU statistics (last 30 days)
            cur.execute("""
                SELECT 
                    event_date,
                    SUM(launch_count) as daily_total
                FROM daily_active_users
                WHERE event_date >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY event_date
                ORDER BY event_date DESC
            """)
            dau_daily = cur.fetchall()
            
            # DAU by hour (last 7 days)
            cur.execute("""
                SELECT 
                    event_hour,
                    AVG(launch_count) as avg_launches,
                    MAX(launch_count) as peak_launches
                FROM daily_active_users
                WHERE event_date >= CURRENT_DATE - INTERVAL '7 days'
                GROUP BY event_hour
                ORDER BY event_hour
            """)
            dau_hourly = cur.fetchall()
            
            # Medication adherence statistics
            cur.execute("""
                SELECT 
                    COUNT(*) as total_medications
                FROM medications
            """)
            total_meds = cur.fetchone()['count']
            
            # Recent survey responses (aggregated)
            cur.execute("""
                SELECT 
                    completion_date,
                    COUNT(*) as responses_count,
                    result_bucket
                FROM survey_responses
                WHERE completion_date >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY completion_date, result_bucket
                ORDER BY completion_date DESC
                LIMIT 50
            """)
            recent_surveys = cur.fetchall()
        
        # Process survey data
        survey_stats = {
            'unique_respondents': 0,
            'total_responses': 0,
            'by_day': {},
            'by_bucket': {'Low': 0, 'Medium': 0, 'High': 0}
        }
        
        if survey_data:
            survey_stats['unique_respondents'] = survey_data[0].get('unique_respondents', 0) if survey_data else 0
            survey_stats['total_responses'] = sum(r['count'] for r in survey_data)
            
            for row in survey_data:
                day_key = f"Day {row['survey_day']}"
                if day_key not in survey_stats['by_day']:
                    survey_stats['by_day'][day_key] = {'Low': 0, 'Medium': 0, 'High': 0, 'total': 0}
                survey_stats['by_day'][day_key][row['result_bucket']] = row['count']
                survey_stats['by_day'][day_key]['total'] += row['count']
                survey_stats['by_bucket'][row['result_bucket']] += row['count']
        
        # Calculate survey improvement metric
        improvement_percentage = 0
        if 'Day 30' in survey_stats['by_day'] and 'Day 90' in survey_stats['by_day']:
            day30_high = survey_stats['by_day']['Day 30'].get('High', 0)
            day30_total = survey_stats['by_day']['Day 30']['total']
            day90_high = survey_stats['by_day']['Day 90'].get('High', 0)
            day90_total = survey_stats['by_day']['Day 90']['total']
            
            if day30_total > 0 and day90_total > 0:
                day30_high_pct = (day30_high / day30_total) * 100
                day90_high_pct = (day90_high / day90_total) * 100
                improvement_percentage = day30_high_pct - day90_high_pct
        
        stats = {
            'accounts': {
                'total_patients': total_patients,
                'total_caregivers': total_caregivers,
                'active_users': active_users,
                'total_medications': total_meds
            },
            'survey': {
                **survey_stats,
                'improvement_percentage': round(improvement_percentage, 1),
                'recent_responses': [
                    {
                        'date': str(r['completion_date']),
                        'count': r['responses_count'],
                        'bucket': r['result_bucket']
                    } for r in recent_surveys
                ]
            },
            'dau': {
                'daily_totals': [
                    {'date': str(r['event_date']), 'count': r['daily_total']} 
                    for r in dau_daily
                ],
                'hourly_average': [
                    {
                        'hour': r['event_hour'], 
                        'avg': float(r['avg_launches']), 
                        'peak': r['peak_launches']
                    } 
                    for r in dau_hourly
                ],
                'total_days_tracked': len(dau_daily),
                'avg_daily_users': round(sum(r['daily_total'] for r in dau_daily) / len(dau_daily), 1) if dau_daily else 0
            }
        }
        
        return jsonify({'success': True, 'stats': stats}), 200
        
    except Exception as e:
        logger.error(f"Admin dashboard stats error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check_noapi():
    return health_check()

# ==================== CONTACT FORM ====================

@app.route('/api/contact', methods=['POST'])
def contact_form():
    """Handle contact form submissions and forward to Google Forms"""
    try:
        import requests
        
        data = request.json
        name = data.get('name', '')
        email = data.get('email', '')
        subject = data.get('subject', '')
        message = data.get('message', '')
        
        # Google Forms URL - we'll use iframe method
        # Create an invisible form submission
        google_form_url = "https://docs.google.com/forms/d/e/1FAIpQLSdGvoST8Q_FbQMhx3Va9CViypuhfp8dnbCqmXPTkXraX27Ljw/formResponse"
        
        # Note: You need to inspect your Google Form to get the correct entry IDs
        # For now, save to database as backup
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contact_submissions (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    message TEXT,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                INSERT INTO contact_submissions (name, email, subject, message)
                VALUES (%s, %s, %s, %s)
            """, (name, email, subject, message))
            conn.commit()
        
        logger.info(f"Contact form submission from {email}")
        
        # Return the Google Form URL for client-side submission
        return jsonify({
            'success': True, 
            'message': 'Thank you for your interest!',
            'redirect': f'https://docs.google.com/forms/d/e/1FAIpQLSdGvoST8Q_FbQMhx3Va9CViypuhfp8dnbCqmXPTkXraX27Ljw/formResponse?entry.NAME={name}&entry.EMAIL={email}&entry.SUBJECT={subject}&entry.MESSAGE={message}'
        }), 200
        
    except Exception as e:
        logger.error(f"Contact form error: {e}")
        return jsonify({'error': 'Failed to submit'}), 500


@app.route('/api/alarms/followup', methods=['POST', 'GET'])
def followup_call():
    """10-minute follow-up call to check if medication was taken"""
    try:
        now = datetime.now(timezone.utc)
        ten_mins_ago = now - timedelta(minutes=10)
        
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            # ✅ FIXED: Check last_called timestamp, not scheduled time
            cur.execute("""
                SELECT id, code_hash, medication_name, time, phone_number
                FROM medication_reminders 
                WHERE active = true 
                AND last_called IS NOT NULL
                AND last_called BETWEEN %s AND %s
                AND NOT EXISTS (
                    SELECT 1 FROM medication_taken 
                    WHERE medication_taken.code_hash = medication_reminders.code_hash
                    AND medication_taken.medication_name = medication_reminders.medication_name
                    AND DATE(medication_taken.taken_at) = CURRENT_DATE
                )
            """, (ten_mins_ago - timedelta(minutes=1), ten_mins_ago + timedelta(minutes=1)))
            
            alarms = cur.fetchall()
            
            if not alarms:
                logger.info(f"📞 No follow-up calls needed")
                return jsonify({'success': True, 'followups': 0}), 200
            
            calls_made = 0
            
            for alarm in alarms:
                alarm_id, code_hash, med_name, time_str, phone = alarm
                
                try:
                    from twilio.rest import Client
                    
                    account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
                    auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
                    twilio_phone = os.environ.get('TWILIO_PHONE_NUMBER')
                    
                    if account_sid and auth_token and twilio_phone:
                        client = Client(account_sid, auth_token)
                        
                        twiml_url = f"https://loveuad.com/api/twilio/followup-voice?med={med_name}&time={time_str}&hash={code_hash}"
                        
                        call = client.calls.create(
                            to=phone,
                            from_=twilio_phone,
                            url=twiml_url,
                            method='POST'
                        )
                        
                        logger.info(f"📞 Follow-up call made: {call.sid} for {med_name}")
                        calls_made += 1
                    else:
                        logger.warning("Twilio not configured")
                        
                except Exception as call_error:
                    logger.error(f"Twilio follow-up error: {call_error}")
            
            conn.commit()
            
            logger.info(f"✓ Follow-up check complete: {calls_made} calls made")
            return jsonify({
                'success': True, 
                'followups': calls_made,
                'checked': len(alarms)
            }), 200
            
    except Exception as e:
        logger.error(f"Follow-up error: {e}")
        return jsonify({'error': str(e)}), 500


def make_followup_call(phone, medication_name, time, code_hash):
    """Make Twilio follow-up call"""
    try:
        call = twilio_client.calls.create(
            to=phone,
            from_=TWILIO_PHONE,
            url=f"{API_BASE_URL}/api/twilio/followup-voice?med={medication_name}&time={time}&hash={code_hash}"
        )
        logger.info(f"📞 Follow-up call to {phone} for {medication_name}")
    except Exception as e:
        logger.error(f"Twilio follow-up error: {e}")


@app.route('/api/twilio/followup-voice', methods=['POST'])
def followup_voice():
    """Handle follow-up call voice response"""
    from flask import request
    from twilio.twiml.voice_response import VoiceResponse, Gather
    
    response = VoiceResponse()
    med_name = request.args.get('med')
    time_str = request.args.get('time')
    code_hash = request.args.get('hash')
    
    # Check if patient responded
    speech_result = request.form.get('SpeechResult', '').lower()
    
    if not speech_result:
        # First call - ask question
        gather = Gather(input='speech', action=f'/api/twilio/followup-voice?med={med_name}&time={time_str}&hash={code_hash}', method='POST')
        gather.say(f"Did you take your {med_name}? Please say yes or no.")
        response.append(gather)
    else:
        # Patient responded
        if 'yes' in speech_result:
            # Mark as taken
            with db_manager.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT encrypted_data FROM patients WHERE code_hash = %s", (code_hash,))
                patient = cur.fetchone()
                
                patient_data = decrypt_data(patient['encrypted_data'])
                adherence = patient_data.get('medicationAdherence', [])
                
                adherence.append({
                    'medication': med_name,
                    'scheduledTime': time_str,
                    'takenAt': datetime.now().isoformat(),
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'status': 'taken'
                })
                
                patient_data['medicationAdherence'] = adherence[-100:]
                encrypted = encrypt_data(patient_data)
                cur.execute("UPDATE patients SET encrypted_data = %s WHERE code_hash = %s", (encrypted, code_hash))
                conn.commit()
            
            response.say("Thank you. Medication marked as taken.")
        else:
            response.say("Understood. Stay safe.")
    
    return str(response)


@app.route('/api/twilio/followup-response', methods=['POST'])
def followup_response():
    """Handle follow-up call speech response"""
    speech_result = request.form.get('SpeechResult', '').lower()
    code_hash = request.args.get('hash')
    med_name = request.args.get('med')
    time = request.args.get('time')
    
    response = VoiceResponse()
    
    # Check for "yes" variations
    if 'yes' in speech_result or 'yeah' in speech_result or 'yep' in speech_result:
        try:
            with db_manager.get_connection() as conn:
                cur = conn.cursor()
                
                # ✅ Insert into medication_taken table
                cur.execute("""
                    INSERT INTO medication_taken (code_hash, medication_name, scheduled_time, taken_at, status)
                    VALUES (%s, %s, %s, %s, 'taken')
                """, (code_hash, med_name, time, datetime.now(timezone.utc)))
                
                # ✅ ALSO update patient's encrypted_data with adherence record
                cur.execute("SELECT encrypted_data FROM patients WHERE code_hash = %s", (code_hash,))
                patient = cur.fetchone()
                
                if patient:
                    patient_data = decrypt_data(patient['encrypted_data'])
                    adherence_history = patient_data.get('medicationAdherence', [])
                    
                    adherence_record = {
                        'medication': med_name,
                        'scheduledTime': time,
                        'takenAt': datetime.now(timezone.utc).isoformat(),
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'status': 'taken',
                        'method': 'phone_followup'
                    }
                    
                    adherence_history.append(adherence_record)
                    patient_data['medicationAdherence'] = adherence_history[-270:]  # Keep last 90 days
                    
                    encrypted_data = encrypt_data(patient_data)
                    cur.execute(
                        "UPDATE patients SET encrypted_data = %s WHERE code_hash = %s",
                        (encrypted_data, code_hash)
                    )
                
                conn.commit()
                logger.info(f"✓ Medication marked as taken via follow-up call: {med_name} at {time}")
            
            response.say("Thank you. Your medication has been marked as taken.", voice='Polly.Joanna')
        
        except Exception as e:
            logger.error(f"Error marking medication taken: {e}")
            response.say("Sorry, there was an error. Please contact your caregiver.", voice='Polly.Joanna')
    
    # Check for "no" variations
    elif 'no' in speech_result or 'nope' in speech_result or 'not' in speech_result:
        response.say("Please remember to take your medication as soon as possible.", voice='Polly.Joanna')
    
    else:
        response.say("Sorry, I didn't understand. Please contact your caregiver if you need help.", voice='Polly.Joanna')
    
    return str(response), 200, {'Content-Type': 'text/xml'}

# ==================== END OF DUPLICATE ROUTES ====================

def reset_daily_reminders():
    """
    Resets the 'daily_status' for all medication reminders back to PENDING.
    This function is called automatically by APScheduler every day at midnight (00:00).
    """
    try:
        # ✅ FIX: Use context manager instead of direct conn access
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE medication_reminders 
                SET daily_status = 'PENDING'
            """)
            conn.commit()
            logger.info("🟢 SCHEDULER: Daily reminder statuses reset to PENDING.")
            
    except Exception as e:
        logger.error(f"❌ SCHEDULER ERROR: Could not reset daily status: {e}")

# Initialize and Start the scheduler
scheduler = BackgroundScheduler()

# Add the job: Run reset_daily_reminders every day at 00:00 (midnight)
scheduler.add_job(
    reset_daily_reminders, 
    'cron', 
    hour=0, 
    minute=0, 
    id='daily_reset_job', 
    replace_existing=True
)

# Start the scheduler when the app starts
scheduler.start()

# ==================== NEW ENDPOINT: Get Alarm Status ====================

@app.route('/api/alarms/status/<code_hash>', methods=['GET'])
def get_alarm_status(code_hash):
    """Get today's medication reminder status for debugging"""
    try:
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            
            cur.execute("""
                SELECT 
                    medication_name,
                    time::text as scheduled_time,
                    daily_status,
                    last_called,
                    active
                FROM medication_reminders 
                WHERE code_hash = %s 
                ORDER BY time
            """, (code_hash,))
            
            alarms = cur.fetchall()
            
            status_summary = {
                'PENDING': 0,
                'REMINDED': 0,
                'FOLLOWUP': 0,
                'TAKEN': 0
            }
            
            alarm_list = []
            for alarm in alarms:
                alarm_dict = dict(alarm)
                alarm_list.append(alarm_dict)
                status_summary[alarm_dict['daily_status']] += 1
            
            return jsonify({
                'success': True,
                'alarms': alarm_list,
                'summary': status_summary
            }), 200
            
    except Exception as e:
        logger.error(f"Get alarm status error: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== MAIN ====================

if __name__ == '__main__':
    logger.info("="*60)
    logger.info("loveUAD - Privacy-First Dementia Care Support")
    logger.info("="*60)
    logger.info("17-digit anonymous codes")
    logger.info("End-to-end encryption")
    logger.info("PII filtering on scans")
    logger.info("RAG-powered dementia guidance")
    logger.info("Research-backed citations")
    logger.info("Google Cloud stack")
    logger.info("✅ MEDICATION REMINDER STATUS TRACKING ENABLED")
    logger.info("Status Flow: PENDING → REMINDED → FOLLOWUP → TAKEN")
    logger.info("="*60)
    
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)