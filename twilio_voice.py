"""
Twilio Voice Chat System for LoveUAD
Voice-powered medication reminders with Gemini AI understanding
"""
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather
from flask import request, jsonify
import os
import logging
from datetime import datetime
import google.generativeai as genai

logger = logging.getLogger(__name__)

# Initialize Twilio
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')

if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
    logger.warning("⚠️ Twilio credentials not configured")
    twilio_client = None
else:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    logger.info("✓ Twilio voice system initialized")

# Initialize Gemini for understanding responses
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
else:
    gemini_model = None
    logger.warning("⚠️ Gemini not configured - using basic keyword matching")


def make_medication_call(phone_number, medication_name, dosage, code_hash, scheduled_time):
    """Make initial medication reminder call"""
    if not twilio_client:
        raise Exception("Twilio not configured")
    
    base_url = os.environ.get('BASE_URL', 'https://loveuad.com')
    
    twiml_url = f"{base_url}/api/twilio/twiml/medication?medication={medication_name}&dosage={dosage}&codeHash={code_hash}&time={scheduled_time}"
    
    call = twilio_client.calls.create(
        to=phone_number,
        from_=TWILIO_PHONE_NUMBER,
        url=twiml_url,
        method='GET',
        status_callback=f"{base_url}/api/twilio/webhook/status"
    )
    
    logger.info(f"📞 Call initiated: {call.sid} to {phone_number[-4:]}")
    return call.sid


def make_followup_call(phone_number, medication_name, code_hash, scheduled_time):
    """Make follow-up call"""
    if not twilio_client:
        raise Exception("Twilio not configured")
    
    base_url = os.environ.get('BASE_URL', 'https://loveuad.com')
    
    twiml_url = f"{base_url}/api/twilio/twiml/followup?medication={medication_name}&codeHash={code_hash}&time={scheduled_time}"
    
    call = twilio_client.calls.create(
        to=phone_number,
        from_=TWILIO_PHONE_NUMBER,
        url=twiml_url,
        method='GET'
    )
    
    logger.info(f"📞 Follow-up call: {call.sid}")
    return call.sid


def generate_medication_twiml(medication, dosage, code_hash, scheduled_time):
    """Generate TwiML for medication reminder - VOICE INPUT"""
    response = VoiceResponse()
    
    base_url = os.environ.get('BASE_URL', 'https://loveuad.com')
    
    # Use Gather with speech recognition
    gather = Gather(
        input='speech',
        action=f'{base_url}/api/twilio/callback/medication?codeHash={code_hash}&medication={medication}&time={scheduled_time}',
        method='POST',
        timeout=5,
        speech_timeout='auto',
        language='en-US'
    )
    
    # Natural conversational message
    message = f"Hello! This is your medication reminder. It's time to take your {medication}"
    if dosage:
        message += f", {dosage}"
    message += ". Have you taken it? Just say yes or no."
    
    gather.say(message, voice='alice', language='en-US')
    response.append(gather)
    
    # If no response, say goodbye
    response.say("I didn't hear you. Please call back when you take your medication. Goodbye.", voice='alice')
    
    return str(response)


def generate_followup_twiml(medication, code_hash, scheduled_time):
    """Generate TwiML for follow-up - VOICE INPUT"""
    response = VoiceResponse()
    
    base_url = os.environ.get('BASE_URL', 'https://loveuad.com')
    
    gather = Gather(
        input='speech',
        action=f'{base_url}/api/twilio/callback/followup?codeHash={code_hash}&medication={medication}&time={scheduled_time}',
        method='POST',
        timeout=5,
        speech_timeout='auto',
        language='en-US'
    )
    
    message = f"Hello, this is a follow-up. Did you take your {medication}? Please say yes or no."
    gather.say(message, voice='alice', language='en-US')
    response.append(gather)
    
    response.say("I didn't hear you. Goodbye.", voice='alice')
    
    return str(response)


def understand_response(speech_text):
    """
    Use Gemini to understand if patient said they took medication
    Returns: 'yes', 'no', or 'unclear'
    """
    if not speech_text:
        return 'unclear'
    
    speech_lower = speech_text.lower().strip()
    
    # Quick keyword check first
    yes_keywords = ['yes', 'yeah', 'yep', 'i took it', 'taken', 'i have', 'already took', 'done']
    no_keywords = ['no', 'not yet', 'haven\'t', 'didn\'t take', 'forgot', 'later']
    
    if any(word in speech_lower for word in yes_keywords):
        return 'yes'
    if any(word in speech_lower for word in no_keywords):
        return 'no'
    
    # Use Gemini for unclear responses
    if gemini_model:
        try:
            prompt = f"""The patient was asked: "Did you take your medication?"
They said: "{speech_text}"

Respond with ONLY ONE WORD:
- "yes" if they confirmed taking it
- "no" if they said they didn't take it
- "unclear" if you cannot determine

Response:"""
            
            result = gemini_model.generate_content(prompt)
            answer = result.text.strip().lower()
            
            if answer in ['yes', 'no', 'unclear']:
                return answer
        except Exception as e:
            logger.error(f"Gemini understanding error: {e}")
    
    return 'unclear'


def handle_medication_callback(speech_result, code_hash, medication, scheduled_time, db_manager):
    """Handle voice response from patient"""
    response = VoiceResponse()
    
    # Get the speech text
    speech_text = speech_result.get('SpeechResult', '')
    confidence = speech_result.get('Confidence', 0)
    
    logger.info(f"Patient said: '{speech_text}' (confidence: {confidence})")
    
    # Understand the response
    understood = understand_response(speech_text)
    
    if understood == 'yes':
        # Patient took medication
        response.say("Wonderful! Your medication has been recorded. Have a great day!", voice='alice')
        
        # Record in database
        try:
            from encryption import encrypt_data, decrypt_data
            
            patient = db_manager.get_patient_data(code_hash)
            if patient:
                patient_data = decrypt_data(patient['encrypted_data'])
                adherence_history = patient_data.get('medicationAdherence', [])
                
                adherence_record = {
                    'medication': medication,
                    'scheduledTime': scheduled_time,
                    'takenAt': datetime.utcnow().isoformat(),
                    'date': datetime.utcnow().strftime('%Y-%m-%d'),
                    'status': 'taken',
                    'takenVia': 'twilio_voice_call',
                    'speechText': speech_text
                }
                
                adherence_history.append(adherence_record)
                patient_data['medicationAdherence'] = adherence_history[-270:]
                
                encrypted_data = encrypt_data(patient_data)
                with db_manager.conn.cursor() as cur:
                    cur.execute(
                        "UPDATE patients SET encrypted_data = %s WHERE code_hash = %s",
                        (encrypted_data, code_hash)
                    )
                    db_manager.conn.commit()
                
                logger.info(f"✓ Medication recorded via voice: {medication}")
        except Exception as e:
            logger.error(f"Database error: {e}")
    
    elif understood == 'no':
        # Patient hasn't taken it
        response.say("Okay. Please take your medication as soon as possible. We'll check back with you soon. Goodbye.", voice='alice')
        logger.info(f"⚠️ Patient said NO: {medication}")
    
    else:
        # Unclear response
        response.say("I didn't quite understand. If you've taken your medication, you're all set. If not, please take it soon. Goodbye.", voice='alice')
        logger.warning(f"Unclear response: '{speech_text}'")
    
    return str(response)


def handle_followup_callback(speech_result, code_hash, medication, scheduled_time, db_manager):
    """Handle voice response from follow-up call"""
    response = VoiceResponse()
    
    speech_text = speech_result.get('SpeechResult', '')
    understood = understand_response(speech_text)
    
    if understood == 'yes':
        response.say("Thank you for confirming! Your medication has been recorded.", voice='alice')
        
        # Record it
        try:
            from encryption import encrypt_data, decrypt_data
            
            patient = db_manager.get_patient_data(code_hash)
            if patient:
                patient_data = decrypt_data(patient['encrypted_data'])
                adherence_history = patient_data.get('medicationAdherence', [])
                
                adherence_record = {
                    'medication': medication,
                    'scheduledTime': scheduled_time,
                    'takenAt': datetime.utcnow().isoformat(),
                    'date': datetime.utcnow().strftime('%Y-%m-%d'),
                    'status': 'taken',
                    'takenVia': 'twilio_followup_call',
                    'speechText': speech_text
                }
                
                adherence_history.append(adherence_record)
                patient_data['medicationAdherence'] = adherence_history[-270:]
                
                encrypted_data = encrypt_data(patient_data)
                with db_manager.conn.cursor() as cur:
                    cur.execute(
                        "UPDATE patients SET encrypted_data = %s WHERE code_hash = %s",
                        (encrypted_data, code_hash)
                    )
                    db_manager.conn.commit()
        except Exception as e:
            logger.error(f"Database error: {e}")
    
    elif understood == 'no':
        response.say("Please take your medication as soon as you can. We'll notify your caregiver. Take care.", voice='alice')
        # TODO: Alert caregiver
    
    else:
        response.say("I couldn't understand your response. Please make sure to take your medication. Goodbye.", voice='alice')
    
    return str(response)
