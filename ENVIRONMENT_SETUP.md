# Environment Variables Setup Guide

## ElevenLabs API Key

### How to Get Your ElevenLabs API Key:

1. **Sign Up / Log In**
   - Go to [ElevenLabs](https://elevenlabs.io/)
   - Create an account or log in

2. **Get Your API Key**
   - Navigate to your Profile Settings
   - Click on "API Keys" section
   - Copy your API key

3. **Add to Your Project**
   - Create a `.env` file in the project root (copy from `.env.example`)
   - Add the line:
     ```
     ELEVENLABS_API_KEY=your_actual_api_key_here
     ```

---

## Complete Environment Setup

### Step 1: Create `.env` File

```bash
# Copy the example file
cp .env.example .env

# Edit the .env file with your actual values
```

### Step 2: Required Environment Variables

| Variable | Description | Where to Get It |
|----------|-------------|-----------------|
| `GEMINI_API_KEY` | Google Gemini API | [Google AI Studio](https://makersuite.google.com/app/apikey) |
| `ELEVENLABS_API_KEY` | ElevenLabs Voice API | [ElevenLabs Dashboard](https://elevenlabs.io/) |
| `DB_PASSWORD` | PostgreSQL Database Password | Your Cloud SQL instance |
| `GCP_PROJECT_ID` | Google Cloud Project ID | [GCP Console](https://console.cloud.google.com/) |
| `INSTANCE_CONNECTION_NAME` | Cloud SQL Connection Name | Format: `project:region:instance` |

### Step 3: Optional Variables (If Using Twilio)

| Variable | Description |
|----------|-------------|
| `TWILIO_ACCOUNT_SID` | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token |
| `TWILIO_PHONE_NUMBER` | Your Twilio Phone Number |

---

## Local Development Setup

### Using `.env` File:

```bash
# 1. Copy example file
cp .env.example .env

# 2. Edit .env with your values
nano .env  # or use your preferred editor

# 3. Set ENVIRONMENT to local
ENVIRONMENT=local

# 4. The app will automatically load .env variables
python app.py
```

### Example `.env` for Local Development:

```bash
# Local Development Configuration
ENVIRONMENT=local
SECRET_KEY=dev-secret-key-change-in-production
DEBUG=True

# Google Cloud
GCP_PROJECT_ID=my-loveuad-project
GCP_LOCATION=europe-west2

# API Keys
GEMINI_API_KEY=AIzaSyXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxX
ELEVENLABS_API_KEY=sk_xxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Database (via Cloud SQL Proxy)
DB_USER=postgres
DB_PASSWORD=your_secure_password
DB_NAME=postgres
INSTANCE_CONNECTION_NAME=my-loveuad-project:europe-west2:loveuad-db
```

---

## Production Deployment (Google Cloud Run)

### Set Environment Variables in Cloud Run:

```bash
# Deploy with environment variables
gcloud run deploy loveuad \
  --image gcr.io/your-project/loveuad \
  --platform managed \
  --region europe-west2 \
  --set-env-vars ENVIRONMENT=production \
  --set-env-vars GEMINI_API_KEY=your-key \
  --set-env-vars ELEVENLABS_API_KEY=your-key \
  --set-secrets DB_PASSWORD=db-password:latest \
  --add-cloudsql-instances your-project:europe-west2:instance
```

### Or via Cloud Console:

1. Go to Cloud Run → Your Service
2. Click "Edit & Deploy New Revision"
3. Go to "Variables & Secrets" tab
4. Add each environment variable
5. Deploy

---

## Security Best Practices

### ⚠️ Important:

1. **Never commit `.env` file to git**
   - Already in `.gitignore`
   - Contains sensitive API keys

2. **Use Secret Manager in Production**
   ```bash
   # Store secrets in Google Secret Manager
   echo -n "your-db-password" | \
     gcloud secrets create db-password --data-file=-
   ```

3. **Rotate Keys Regularly**
   - Regenerate API keys every 90 days
   - Update in both `.env` and Cloud Run

4. **Different Keys for Dev/Prod**
   - Use separate API keys for development and production
   - Helps track usage and debug issues

---

## Testing Your Setup

### Test ElevenLabs Connection:

```python
# test_elevenlabs.py
import os
from dotenv import load_dotenv
from elevenlabs import ElevenLabs

load_dotenv()

client = ElevenLabs(api_key=os.getenv('ELEVENLABS_API_KEY'))

# Test text-to-speech
audio = client.generate(
    text="Hello! This is a test of the ElevenLabs voice API.",
    voice="Rachel",
    model="eleven_turbo_v2_5"
)

print("✅ ElevenLabs connection successful!")
```

### Test Gemini Connection:

```python
# test_gemini.py
import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-2.0-flash-exp')

response = model.generate_content("Say hello")
print("✅ Gemini connection successful!")
print(response.text)
```

---

## Troubleshooting

### Common Issues:

**1. "API key not found" error:**
```bash
# Check if .env file exists
ls -la .env

# Check if python-dotenv is installed
pip install python-dotenv
```

**2. "Invalid API key" error:**
```bash
# Verify your API key in .env
cat .env | grep ELEVENLABS_API_KEY

# Test the key directly on ElevenLabs dashboard
```

**3. "Database connection failed":**
```bash
# For local development, start Cloud SQL Proxy
./cloud_sql_proxy -instances=PROJECT:REGION:INSTANCE=tcp:5432
```

**4. Environment variables not loading:**
```python
# Add debug code to check if .env is loaded
import os
from dotenv import load_dotenv

load_dotenv()
print("API Key loaded:", os.getenv('ELEVENLABS_API_KEY')[:10] + "...")
```

---

## Quick Reference

### In Python Code:

```python
from config import Config

# Access ElevenLabs API key
api_key = Config.ELEVENLABS_API_KEY

# Use in ElevenLabs client
from elevenlabs import ElevenLabs
client = ElevenLabs(api_key=Config.ELEVENLABS_API_KEY)
```

### Environment Variable Naming Convention:

- **Uppercase with underscores**: `ELEVENLABS_API_KEY`
- **Descriptive names**: `DB_PASSWORD` not `PWD`
- **Service prefix**: `TWILIO_`, `GCP_`, etc.

---

## Next Steps

1. ✅ Copy `.env.example` to `.env`
2. ✅ Get your ElevenLabs API key
3. ✅ Fill in all required variables
4. ✅ Test the connection
5. ✅ Run the app locally
6. ✅ Deploy to Cloud Run with environment variables

---

**Need Help?**
- [ElevenLabs Documentation](https://elevenlabs.io/docs)
- [Google Cloud Secret Manager](https://cloud.google.com/secret-manager/docs)
- [Python dotenv Guide](https://pypi.org/project/python-dotenv/)

---

*Last Updated: December 22, 2025*
*loveUAD - CBT Coaching for Caregivers*
