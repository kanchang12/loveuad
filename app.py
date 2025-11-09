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
if not Config.GEMINI_API_KEY:
    logger.warning("⚠️ GEMINI_API_KEY not set - OCR and AI features will fail")
    vision_model = None
else:
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

@app.route('/patient/register', methods=['POST'])
def register_patient_noapi():
    return register_patient()

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
        with db_manager.conn.cursor() as cur:
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
        with db_manager.conn.cursor() as cur:
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

@app.route('/medications/delete', methods=['POST'])
def delete_medication_noapi():
    return delete_medication()

@app.route('/medications/schedule', methods=['POST'])
def schedule_medications_noapi():
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

@app.route('/scan/prescription', methods=['POST'])
def scan_prescription_noapi():
    return scan_prescription()

@app.route('/health/records/<code_hash>', methods=['GET'])
def get_health_records_noapi(code_hash):
    return get_health_records(code_hash)

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
        db_manager.insert_health_record(code_hash, encrypted_metadata, record_date)
        
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
        
        return jsonify({
            'success': True,
            'ocrResult': {
                'raw_text': filtered_text,
                'extracted_data': {'medications': medications},
                'ai_insights': ai_insights
            }
        }), 200
    except Exception as e:
        logger.error(f"OCR error: {e}")
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
        
        with db_manager.conn.cursor() as cur:
            cur.execute("UPDATE patients SET encrypted_data = %s WHERE code_hash = %s;", 
                       (encrypted_data, code_hash))
            db_manager.conn.commit()
        
        return jsonify({'success': True, 'tier': tier}), 200
    except Exception as e:
        logger.error(f"Tier update error: {e}")
        return jsonify({'error': 'Failed'}), 500

@app.route('/health', methods=['GET'])
def health_check_noapi():
    return health_check()

# ==================== END OF DUPLICATE ROUTES ====================

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
