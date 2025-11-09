from cryptography.fernet import Fernet
from config import Config
import json
import base64
import secrets
import hashlib

# Initialize cipher
cipher = Fernet(Config.ENCRYPTION_KEY.encode() if isinstance(Config.ENCRYPTION_KEY, str) else Config.ENCRYPTION_KEY)

def encrypt_data(data):
    """Encrypt sensitive data"""
    if isinstance(data, dict):
        data = json.dumps(data)
    elif not isinstance(data, str):
        data = str(data)
    encrypted = cipher.encrypt(data.encode())
    return base64.urlsafe_b64encode(encrypted).decode()

def decrypt_data(encrypted_data):
    """Decrypt data"""
    try:
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
        decrypted = cipher.decrypt(encrypted_bytes)
        try:
            return json.loads(decrypted.decode())
        except json.JSONDecodeError:
            return decrypted.decode()
    except Exception as e:
        print(f"Decryption error: {e}")
        return None

def generate_patient_code():
    """Generate 12-character patient code in 4-4-4 format"""
    chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    code = ''.join(secrets.choice(chars) for _ in range(12))
    return f"{code[:4]}-{code[4:8]}-{code[8:12]}"

def hash_patient_code(code):
    """Hash patient code for database - handles both old (17-char) and new (12-char) formats"""
    # Remove dashes for consistent hashing
    clean_code = code.replace('-', '').upper()
    return hashlib.sha256(clean_code.encode()).hexdigest()
