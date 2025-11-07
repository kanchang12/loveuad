# Quick Start Guide

Get loveUAD API running in 30 minutes.

## Prerequisites

- Google Cloud account with billing enabled
- gcloud CLI installed
- Python 3.11+

## Step 1: Setup Google Cloud (5 minutes)

```bash
# Set your project ID
export PROJECT_ID=your-project-id
gcloud config set project $PROJECT_ID

# Enable APIs
gcloud services enable sqladmin.googleapis.com
gcloud services enable aiplatform.googleapis.com
gcloud services enable run.googleapis.com
```

## Step 2: Create Cloud SQL Database (10 minutes)

```bash
# Create instance (f1-micro for cost optimization)
gcloud sql instances create loveuad-db \
    --database-version=POSTGRES_15 \
    --tier=db-f1-micro \
    --region=europe-west2 \
    --root-password=ChangeThisPassword123 \
    --storage-size=10GB

# Create database
gcloud sql databases create loveuad --instance=loveuad-db

# Get connection name
gcloud sql instances describe loveuad-db --format='value(connectionName)'
# Save this - you'll need it
```

## Step 3: Configure Environment (2 minutes)

```bash
# Copy template
cp .env.example .env

# Generate encryption key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Edit .env file with your values
nano .env
```

## Step 4: Deploy to Cloud Run (5 minutes)

```bash
# Make deploy script executable
chmod +x deploy.sh

# Deploy
./deploy.sh
```

## Step 5: Initialize Database (2 minutes)

```bash
# Install Cloud SQL Proxy
gcloud components install cloud-sql-proxy

# Start proxy
cloud_sql_proxy -instances=<YOUR_CONNECTION_NAME>=tcp:5432 &

# Setup database
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python scripts/setup_db.py
```

## Step 6: Load Research Papers (2-3 hours)

```bash
# Ingest your research papers JSON
python scripts/ingest_research.py /path/to/research_papers.json
```

## Test Your API

```bash
# Get your service URL
gcloud run services describe loveuad-api \
    --region europe-west2 \
    --format='value(status.url)'

# Test health endpoint
curl https://your-service-url/api/health
```

## Quick Test Flow

### 1. Register Patient
```bash
curl -X POST https://your-url/api/patient/register \
  -H "Content-Type: application/json" \
  -d '{"firstName":"John","lastName":"Doe","age":75,"gender":"Male"}'
```

### 2. Save the patient code and code hash from response

### 3. Ask Question
```bash
curl -X POST https://your-url/api/dementia/query \
  -H "Content-Type: application/json" \
  -d '{"codeHash":"YOUR_CODE_HASH","query":"How to handle medication refusal?"}'
```

## Troubleshooting

### Database Connection Failed
```bash
# Check Cloud SQL Proxy
ps aux | grep cloud_sql_proxy

# Restart if needed
killall cloud_sql_proxy
cloud_sql_proxy -instances=<CONNECTION_NAME>=tcp:5432 &
```

### Deployment Failed
```bash
# Check logs
gcloud run services logs read loveuad-api --region=europe-west2
```

### API Returns 500
```bash
# Check environment variables are set
gcloud run services describe loveuad-api --region=europe-west2
```

## Next Steps

- Load research papers (scripts/ingest_research.py)
- Connect mobile apps to your API
- Monitor usage in Cloud Console
- Set up Cloud Logging

## Need Help?

See full README.md for detailed documentation.
