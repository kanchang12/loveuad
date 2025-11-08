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

# Initialize Gemini API
genai.configure(api_key=Config.GEMINI_API_KEY)
vision_model = genai.GenerativeModel(Config.VISION_MODEL)

# PII Filter instance
pii_filter = PIIFilter()

# ==================== PATIENT MANAGEMENT ====================

@app.route('/api/patient/register', methods=['POST'])
def register_patient():
    """Register new patient with 17-digit code"""
    try:
        data = request.json
        
        # Generate unique code
        patient_code = generate_patient_code()
        code_hash = hash_patient_code(patient_code)
        
        # Encrypt patient data
        patient_data = {
            'firstName': data.get('firstName'),
            'lastName': data.get('lastName'),
            'age': data.get('age'),
            'gender': data.get('gender'),
            'createdAt': datetime.utcnow().isoformat()
        }
        
        encrypted_data = encrypt_data(patient_data)
        
        # Store in database
        db_manager.insert_patient_data(code_hash, encrypted_data)
        
        return jsonify({
            'success': True,
            'patientCode': patient_code,
            'codeHash': code_hash
        }), 201
    
    except Exception as e:
        logger.error(f"Registration error: {e}")
        return jsonify({'error': 'Registration failed'}), 500

@app.route('/api/patient/login', methods=['POST'])
def login_patient():
    """Login with 17-digit code"""
    try:
        data = request.json
        patient_code = data.get('patientCode')
        
        if not patient_code:
            return jsonify({'error': 'Patient code required'}), 400
        
        code_hash = hash_patient_code(patient_code)
        
        # Verify code exists
        patient = db_manager.get_patient_data(code_hash)
        
        if not patient:
            return jsonify({'error': 'Invalid patient code'}), 404
        
        # Decrypt patient data
        patient_data = decrypt_data(patient['encrypted_data'])
        
        return jsonify({
            'success': True,
            'codeHash': code_hash,
            'patient': {
                'firstName': patient_data.get('firstName'),
                'lastName': patient_data.get('lastName'),
                'age': patient_data.get('age'),
                'gender': patient_data.get('gender')
            }
        }), 200
    
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'error': 'Login failed'}), 500

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

@app.route('/api/medications/<code_hash>', methods=['GET'])
def get_medications(code_hash):
    """Get all active medications for patient"""
    try:
        medications = db_manager.get_medications(code_hash)
        
        decrypted_meds = [decrypt_data(med['encrypted_data']) for med in medications]
        
        return jsonify({
            'success': True,
            'medications': decrypted_meds
        }), 200
    
    except Exception as e:
        logger.error(f"Get medications error: {e}")
        return jsonify({'error': 'Failed to fetch medications'}), 500

@app.route('/api/medications/update', methods=['POST'])
def update_medication():
    """Update medication"""
    try:
        data = request.json
        code_hash = data.get('codeHash')
        medication = data.get('medication')
        
        if not code_hash or not medication:
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Get all medications
        medications = db_manager.get_medications(code_hash)
        
        # Find and update the medication
        for med_record in medications:
            decrypted = decrypt_data(med_record['encrypted_data'])
            if decrypted['name'] == medication['name']:
                medication['updatedAt'] = datetime.utcnow().isoformat()
                encrypted_data = encrypt_data(medication)
                
                with db_manager.conn.cursor() as cur:
                    cur.execute("""
                        UPDATE medications 
                        SET encrypted_data = %s 
                        WHERE id = %s;
                    """, (encrypted_data, med_record['id']))
                    db_manager.conn.commit()
                
                return jsonify({'success': True, 'message': 'Medication updated'}), 200
        
        return jsonify({'error': 'Medication not found'}), 404
    
    except Exception as e:
        logger.error(f"Update medication error: {e}")
        return jsonify({'error': 'Failed to update medication'}), 500

@app.route('/api/medications/delete', methods=['POST'])
def delete_medication():
    """Mark medication as inactive"""
    try:
        data = request.json
        code_hash = data.get('codeHash')
        medication_name = data.get('medicationName')
        
        if not code_hash or not medication_name:
            return jsonify({'error': 'Missing required fields'}), 400
        
        medications = db_manager.get_medications(code_hash)
        
        for med_record in medications:
            decrypted = decrypt_data(med_record['encrypted_data'])
            if decrypted['name'] == medication_name:
                with db_manager.conn.cursor() as cur:
                    cur.execute("""
                        UPDATE medications 
                        SET active = FALSE 
                        WHERE id = %s;
                    """, (med_record['id'],))
                    db_manager.conn.commit()
                
                return jsonify({'success': True, 'message': 'Medication deleted'}), 200
        
        return jsonify({'error': 'Medication not found'}), 404
    
    except Exception as e:
        logger.error(f"Delete medication error: {e}")
        return jsonify({'error': 'Failed to delete medication'}), 500

# ==================== PRESCRIPTION SCANNING ====================

@app.route('/api/scan/prescription', methods=['POST'])
def scan_prescription():
    """Scan prescription using Gemini Vision with PII filtering"""
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
        # Convert bytes to PIL Image
        image = Image.open(io.BytesIO(image_bytes))
        response = vision_model.generate_content([prompt, image])
        
        ocr_text = response.text
        
        # Filter PII
        filtered_text = pii_filter.remove_pii(ocr_text)
        
        # AI Analysis with Gemini
        analysis_prompt = f"""Analyze this prescription and provide guidance:

Prescription Text:
{filtered_text}

Provide:
1. Medication summary
2. Important warnings
3. Potential side effects
4. Storage instructions
5. Any concerns for dementia patients

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
            'ai_analysis': ai_analysis
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
        with db_manager.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO caregiver_connections 
                (caregiver_id, patient_code_hash, patient_nickname)
                VALUES (%s, %s, %s);
            """, (caregiver_id, code_hash, patient_nickname))
            db_manager.conn.commit()
        
        return jsonify({'success': True}), 201
    
    except Exception as e:
        logger.error(f"Connection error: {e}")
        return jsonify({'error': 'Connection failed'}), 500

# ==================== DEMENTIA RAG ENDPOINTS ====================

@app.route('/api/dementia/query', methods=['POST'])
def dementia_query():
    """Get dementia guidance with research citations"""
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
        
        # Get RAG response
        rag_response = rag_pipeline.get_response(query)
        
        # Encrypt and store conversation
        encrypted_query = encrypt_data(query)
        encrypted_response = encrypt_data(rag_response['answer'])
        
        db_manager.insert_conversation(
            code_hash,
            encrypted_query,
            encrypted_response,
            rag_response['sources']
        )
        
        return jsonify({
            'success': True,
            'answer': rag_response['answer'],
            'sources': rag_response['sources'],
            'disclaimer': 'This guidance is based on research. Always consult healthcare professionals for medical advice.'
        }), 200
    
    except Exception as e:
        logger.error(f"Dementia query error: {e}")
        return jsonify({'error': 'Query failed'}), 500

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

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

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
    logger.info("="*60)
    
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
