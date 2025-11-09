-- ============================================================
-- CREATE ALL DATABASE TABLES
-- Run this to create the complete database schema
-- ============================================================

-- 1. PATIENTS TABLE
CREATE TABLE IF NOT EXISTS patients (
    id SERIAL PRIMARY KEY,
    code_hash VARCHAR(255) UNIQUE NOT NULL,
    encrypted_data BYTEA NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_patients_code_hash ON patients(code_hash);

-- 2. MEDICATIONS TABLE
CREATE TABLE IF NOT EXISTS medications (
    id SERIAL PRIMARY KEY,
    patient_code_hash VARCHAR(255) NOT NULL,
    encrypted_data BYTEA NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_code_hash) REFERENCES patients(code_hash) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_medications_patient ON medications(patient_code_hash);
CREATE INDEX IF NOT EXISTS idx_medications_active ON medications(active);

-- 3. HEALTH RECORDS TABLE
CREATE TABLE IF NOT EXISTS health_records (
    id SERIAL PRIMARY KEY,
    patient_code_hash VARCHAR(255) NOT NULL,
    record_type VARCHAR(100) NOT NULL,
    encrypted_metadata BYTEA NOT NULL,
    record_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_code_hash) REFERENCES patients(code_hash) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_health_records_patient ON health_records(patient_code_hash);
CREATE INDEX IF NOT EXISTS idx_health_records_type ON health_records(record_type);

-- 4. CAREGIVER CONNECTIONS TABLE
CREATE TABLE IF NOT EXISTS caregiver_connections (
    id SERIAL PRIMARY KEY,
    caregiver_id VARCHAR(255) NOT NULL,
    patient_code_hash VARCHAR(255) NOT NULL,
    patient_nickname VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_code_hash) REFERENCES patients(code_hash) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_caregiver_connections_caregiver ON caregiver_connections(caregiver_id);
CREATE INDEX IF NOT EXISTS idx_caregiver_connections_patient ON caregiver_connections(patient_code_hash);

-- 5. CONVERSATIONS TABLE (for AI dementia chat)
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    patient_code_hash VARCHAR(255) NOT NULL,
    query TEXT NOT NULL,
    response TEXT NOT NULL,
    sources JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_code_hash) REFERENCES patients(code_hash) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversations_patient ON conversations(patient_code_hash);

-- 6. RESEARCH DOCUMENTS TABLE (for RAG)
CREATE TABLE IF NOT EXISTS research_documents (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),
    source VARCHAR(255),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_research_documents_embedding ON research_documents 
USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================================
-- VERIFY TABLES WERE CREATED
-- ============================================================
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public'
ORDER BY table_name;
