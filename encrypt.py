#!/usr/bin/env python3
"""Fix encryption key - run this once"""

from cryptography.fernet import Fernet
import os

print("🔐 Generating encryption key...")

# Generate a new Fernet key
encryption_key = Fernet.generate_key().decode()

print(f"\n✅ Generated encryption key: {encryption_key}\n")

# Try to update config.py
config_path = "config.py"

if os.path.exists(config_path):
    with open(config_path, 'r') as f:
        content = f.read()
    
    # Check if ENCRYPTION_KEY exists
    if 'ENCRYPTION_KEY' in content:
        # Replace existing
        import re
        content = re.sub(
            r'ENCRYPTION_KEY\s*=\s*[^\n]+',
            f'ENCRYPTION_KEY = "{encryption_key}"',
            content
        )
        print("✓ Updated existing ENCRYPTION_KEY in config.py")
    else:
        # Add new
        content += f'\n\n# Encryption Key\nENCRYPTION_KEY = "{encryption_key}"\n'
        print("✓ Added ENCRYPTION_KEY to config.py")
    
    with open(config_path, 'w') as f:
        f.write(content)
    
    print(f"✓ Saved to {config_path}")
else:
    print(f"⚠️  config.py not found. Creating new one...")
    
    config_content = f'''import os

class Config:
    # MongoDB
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    DB_NAME = os.getenv('DB_NAME', 'loveuad')
    
    # Encryption
    ENCRYPTION_KEY = "{encryption_key}"
    
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-change-this')
    
    # Google AI
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
'''
    
    with open(config_path, 'w') as f:
        f.write(config_content)
    
    print(f"✓ Created {config_path}")

print("\n" + "="*60)
print("✅ DONE! Now run: python app.py")
print("="*60)