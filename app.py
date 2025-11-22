from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
from datetime import datetime, timedelta
from PIL import Image
import io
import base64
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

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
CORS(app, supports_credentials=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db_manager = DatabaseManager()
rag_pipeline = RAGPipeline(db_manager)

def init_analytics_tables():
    try:
        with db_manager.conn.cursor() as cur:
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
            db_manager.conn.commit()
            logger.info("✓ Analytics tables initialized")
    except Exception as e:
        logger.warning(f"Analytics tables already exist or error: {e}")

init_analytics_tables()

if not Config.GEMINI_API_KEY:
    logger.warning("⚠️ GEMINI_API_KEY not set - OCR and AI features will fail")
    vision_model = None
else:
    genai.configure(api_key=Config.GEMINI_API_KEY)
    vision_model = genai.GenerativeModel(Config.VISION_MODEL)

pii_filter = PIIFilter()

@app.route('/api/patient/register', methods=['POST'])
def register_patient():
    try:
        data = request.json
        patient_code = generate_patient_code()
        code_hash = hash_patient_code(patient_code)
        logger.info(f"Registering new patient - Code: {patient_code}, Hash: {code_hash[:10]}...")
        
        patient_data = {
            'firstName': data.get('firstName'),
            'lastName': data.get('lastName', ''),
            'age': data.get('age'),
            'gender': data.get('gender'),
            'tier': data.get('tier', 'premium'),
            'createdAt': datetime.utcnow().isoformat()
        }
        
        encrypted_data = encrypt_data(patient_data)
        db_manager.insert_patient_data(code_hash, encrypted_data)
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

@app.route('/api/patient/login', methods=['POST'])
def login_patient():
    try:
        data = request.json
        patient_code = data.get('patientCode')
        
        if not patient_code:
            return jsonify({'error': 'Patient code required'}), 400
        
        clean_code = patient_code.replace('-', '').strip().upper()
        
        if len(clean_code) != 17:
            logger.warning(f"Invalid code length: {len(clean_code)} chars (expected 17)")
            return jsonify({'error': f'Invalid code format. Expected 17 characters (XXXX-XXXX-XXXX-XXXX-X), got {len(clean_code)}'}), 400
        
        code_hash = hash_patient_code(patient_code)
        logger.info(f"Login attempt - Code: {patient_code}, Clean: {clean_code}, Hash: {code_hash[:10]}...")
        
        patient = db_manager.get_patient_data(code_hash)
        
        if not patient:
            logger.warning(f"Patient not found - Code: {patient_code}, Hash: {code_hash}")
            return jsonify({
                'error': 'Invalid patient code - not found in database. If you registered before, please register again with the new 17-character format.'
            }), 404
        
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
        return jsonify({'error': f'Login failed: {str(e)}'}), 500

@app.route('/patient/login', methods=['POST'])
def login_patient_noapi():
    return login_patient()

@app.route('/api/patient/qr/<code>', methods=['GET'])
def generate_qr(code):
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

@app.route('/patient/qr/<code>', methods=['GET'])
def generate_qr_noapi(code):
    return generate_qr(code)

@app.route('/api/medications/add', methods=['POST'])
def add_medication():
    try:
        data = request.json
        code_hash = data.get('codeHash')
        medication = data.get('medication')
        
        if not code_hash or not medication:
            return jsonify({'error': 'Missing required fields'}), 400
        
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Invalid patient code'}), 404
        
        medication['createdAt'] = datetime.utcnow().isoformat()
        encrypted_data = encrypt_data(medication)
        db_manager.insert_medication(code_hash, encrypted_data)
        
        return jsonify({'success': True, 'message': 'Medication added'}), 201
    except Exception as e:
        logger.error(f"Add medication error: {e}")
        return jsonify({'error': 'Failed to add medication'}), 500

@app.route('/medications/add', methods=['POST'])
def add_medication_noapi():
    return add_medication()

@app.route('/api/medications/<code_hash>', methods=['GET'])
def get_medications(code_hash):
    try:
        medications = db_manager.get_medications(code_hash)
        decrypted_meds = [decrypt_data(med['encrypted_data']) for med in medications]
        
        patient = db_manager.get_patient_data(code_hash)
        if patient:
            patient_data = decrypt_data(patient['encrypted_data'])
            adherence_history = patient_data.get('medicationAdherence', [])
            today = datetime.now().strftime('%Y-%m-%d')
            today_adherence = [a for a in adherence_history if a.get('date') == today]
            
            for med in decrypted_meds:
                if 'times' in med:
                    for i, time in enumerate(med['times']):
                        taken = any(
                            a.get('medication') == med['name'] and 
                            a.get('scheduledTime') == time 
                            for a in today_adherence
                        )
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

@app.route('/medications/<code_hash>', methods=['GET'])
def get_medications_noapi(code_hash):
    return get_medications(code_hash)

@app.route('/api/medications/schedule', methods=['POST'])
def schedule_medications():
    try:
        data = request.json
        code_hash = data.get('codeHash')
        medications = data.get('medications')
        
        if not code_hash or not medications:
            return jsonify({'error': 'Missing required fields'}), 400
        
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Invalid patient code'}), 404
        
        for med in medications:
            med['createdAt'] = datetime.utcnow().isoformat()
            encrypted_data = encrypt_data(med)
            db_manager.insert_medication(code_hash, encrypted_data)
        
        return jsonify({'success': True, 'message': f'{len(medications)} medications scheduled'}), 201
    except Exception as e:
        logger.error(f"Schedule error: {e}")
        return jsonify({'error': 'Failed'}), 500

@app.route('/medications/schedule', methods=['POST'])
def schedule_medications_noapi():
    return schedule_medications()

@app.route('/api/health/medication-taken', methods=['POST'])
def record_medication_taken():
    try:
        data = request.json
        code_hash = data.get('codeHash')
        medication_name = data.get('medicationName')
        scheduled_time = data.get('scheduledTime')
        taken_at = data.get('takenAt')
        
        if not all([code_hash, medication_name, scheduled_time, taken_at]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        patient = db_manager.get_patient_data(code_hash)
        if not patient:
            return jsonify({'error': 'Patient not found'}), 404
        
        adherence_record = {
            'medication': medication_name,
            'scheduledTime': scheduled_time,
            'takenAt': taken_at,
            'date': datetime.fromisoformat(taken_at.replace('Z', '+00:00')).strftime('%Y-%m-%d'),
            'status': 'taken'
        }
        
        patient_data = decrypt_data(patient['encrypted_data'])
        adherence_history = patient_data.get('medicationAdherence', [])
        adherence_history.append(adherence_record)
        patient_data['medicationAdherence'] = adherence_history[-270:]
        
        encrypted_data = encrypt_data(patient_data)
        with db_manager.conn.cursor() as cur:
            cur.execute(
                "UPDATE patients SET encrypted_data = %s WHERE code_hash = %s",
                (encrypted_data, code_hash)
            )
            db_manager.conn.commit()
        
        logger.info(f"Medication adherence recorded for patient {code_hash[:8]}...")
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Medication adherence tracking error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/app-launch', methods=['POST'])
def record_app_launch():
    try:
        data = request.json
        code_hash = data.get('codeHash')
        
        if not code_hash:
            return jsonify({'error': 'Missing code'}), 400
        
        now = datetime.now()
        today = now.date()
        current_hour = now.hour
        
        with db_manager.conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM daily_launch_tracker 
                WHERE code_hash = %s AND launch_date = %s
            """, (code_hash, today))
            already_launched_today = cur.fetchone()
            
            if already_launched_today:
                return jsonify({'success': True, 'counted': False}), 200
            
            cur.execute("""
                INSERT INTO daily_launch_tracker (code_hash, launch_date)
                VALUES (%s, %s)
                ON CONFLICT (code_hash, launch_date) DO NOTHING
            """, (code_hash, today))
            
            cur.execute("""
                INSERT INTO daily_active_users (event_date, event_hour, launch_count)
                VALUES (%s, %s, 1)
                ON CONFLICT (event_date, event_hour) 
                DO UPDATE SET launch_count = daily_active_users.launch_count + 1
            """, (today, current_hour))
            
            cur.execute("""
                DELETE FROM daily_launch_tracker 
                WHERE launch_date < %s
            """, (today - timedelta(days=2),))
            
            db_manager.conn.commit()
        
        logger.info(f"DAU recorded: {today} {current_hour}:00")
        return jsonify({'success': True, 'counted': True}), 200
    except Exception as e:
        logger.error(f"App launch tracking error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/analytics', methods=['GET'])
def admin_analytics_page():
    return render_template('admin_analytics.html')

@app.route('/api/admin/verify-password', methods=['POST'])
def verify_admin_password():
    try:
        data = request.json
        password = data.get('password')
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
    try:
        with db_manager.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as count FROM patients")
            total_patients = cur.fetchone()['count']
            
            cur.execute("SELECT COUNT(*) as count FROM medications")
            total_meds = cur.fetchone()['count']
            
            cur.execute("""
                SELECT COUNT(DISTINCT code_hash) as count 
                FROM daily_launch_tracker 
                WHERE launch_date >= CURRENT_DATE - INTERVAL '7 days'
            """)
            active_result = cur.fetchone()
            active_users = active_result['count'] if active_result else 0
            
            cur.execute("""
                SELECT COUNT(*) as total_responses
                FROM survey_responses
            """)
            survey_result = cur.fetchone()
            survey_responses = survey_result['total_responses'] if survey_result else 0
        
        stats = {
            'accounts': {
                'total_patients': total_patients,
                'total_caregivers': 0,
                'active_users': active_users,
                'total_medications': total_meds
            },
            'survey': {
                'total_responses': survey_responses,
                'unique_respondents': 0,
                'by_day': {},
                'by_bucket': {'Low': 0, 'Medium': 0, 'High': 0},
                'improvement_percentage': 0,
                'recent_responses': []
            },
            'dau': {
                'daily_totals': [],
                'hourly_average': [],
                'total_days_tracked': 0,
                'avg_daily_users': 0
            }
        }
        
        return jsonify({'success': True, 'stats': stats}), 200
    except Exception as e:
        logger.error(f"Admin dashboard stats error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route("/", methods=["GET"])
def landing_page():
    return render_template("landing.html")

@app.route("/index.html", methods=["GET"])
def index_page():
    return render_template("index.html")

@app.route("/privacy.html", methods=["GET"])
def privacy_page():
    return render_template("privacy.html")

@app.route("/role-selection-fixed.html", methods=["GET"])
def role_selection_fixed_page():
    return render_template("role-selection-fixed.html")

@app.route("/dashboard.html", methods=["GET"])
def dashboard_page():
    return render_template("dashboard.html")

@app.route("/caregiver-login.html", methods=["GET"])
def caregiver_login_page():
    return render_template("caregiver-login.html")

@app.route("/caregiver-dashboard.html", methods=["GET"])
def caregiver_dashboard_page():
    return render_template("caregiver-dashboard.html")

@app.route("/caregiver-reminders.html", methods=["GET"])
def caregiver_reminders_page():
    return render_template("caregiver-reminders.html")

@app.route("/caregiver-medicines.html", methods=["GET"])
def caregiver_medicines_page():
    return render_template("caregiver-medicines.html")

@app.route("/caregiver-health.html", methods=["GET"])
def caregiver_health_page():
    return render_template("caregiver-health.html")

@app.route("/caregiver-chat.html", methods=["GET"])
def caregiver_chat_page():
    return render_template("caregiver-chat.html")

@app.route("/patient-login.html", methods=["GET"])
def patient_login_page():
    return render_template("patient-login.html")

@app.route("/patient-register.html", methods=["GET"])
def patient_register_page():
    return render_template("patient-register.html")

@app.route("/patient-dashboard.html", methods=["GET"])
def patient_dashboard_page():
    return render_template("patient-dashboard.html")

@app.route("/patient-options.html", methods=["GET"])
def patient_options_page():
    return render_template("patient-options.html")

@app.route("/patient-reminders.html", methods=["GET"])
def patient_reminders_page():
    return render_template("patient-reminders.html")

@app.route("/patient-medicines.html", methods=["GET"])
def patient_medicines_page():
    return render_template("patient-medicines.html")

@app.route("/patient-settings.html", methods=["GET"])
def patient_settings_page():
    return render_template("patient-settings.html")

@app.route("/patient-camera.html", methods=["GET"])
def patient_camera_page():
    return render_template("patient-camera.html")

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'service': 'loveUAD API',
        'version': '1.0.0'
    }), 200

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

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
    logger.info("="*60)
    
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
