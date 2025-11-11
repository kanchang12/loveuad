-- ============================================================
-- RUN THESE COMMANDS IN PostgreSQL TO DROP OTHER DATABASES
-- ============================================================

-- Step 1: Connect to postgres database first
\c postgres

-- Step 2: Terminate all connections to databases you want to drop
SELECT pg_terminate_backend(pg_stat_activity.pid)
FROM pg_stat_activity
WHERE pg_stat_activity.datname IN ('loveuad', 'research')
  AND pid <> pg_backend_pid();

-- Step 3: Drop the databases
DROP DATABASE IF EXISTS loveuad;
DROP DATABASE IF EXISTS research;

-- Step 4: Verify only postgres remains
SELECT datname FROM pg_database WHERE datistemplate = false;

-- Step 5: Create all tables in postgres database
CREATE TABLE IF NOT EXISTS patients (
    id SERIAL PRIMARY KEY,
    code_hash VARCHAR(255) UNIQUE NOT NULL,
    encrypted_data BYTEA NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS medications (
    id SERIAL PRIMARY KEY,
    patient_code_hash VARCHAR(255) NOT NULL,
    encrypted_data BYTEA NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_code_hash) REFERENCES patients(code_hash) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS health_records (
    id SERIAL PRIMARY KEY,
    patient_code_hash VARCHAR(255) NOT NULL,
    record_type VARCHAR(100) NOT NULL,
    encrypted_metadata BYTEA NOT NULL,
    record_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_code_hash) REFERENCES patients(code_hash) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS caregiver_connections (
    id SERIAL PRIMARY KEY,
    caregiver_id VARCHAR(255) NOT NULL,
    patient_code_hash VARCHAR(255) NOT NULL,
    patient_nickname VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_code_hash) REFERENCES patients(code_hash) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    patient_code_hash VARCHAR(255) NOT NULL,
    encrypted_query BYTEA NOT NULL,
    encrypted_response BYTEA NOT NULL,
    sources JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_code_hash) REFERENCES patients(code_hash) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS research_papers (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    authors TEXT,
    journal VARCHAR(255),
    year INTEGER,
    doi VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS paper_chunks (
    id SERIAL PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    chunk_fts TSVECTOR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (paper_id) REFERENCES research_papers(id) ON DELETE CASCADE
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_patients_code_hash ON patients(code_hash);
CREATE INDEX IF NOT EXISTS idx_medications_patient ON medications(patient_code_hash);
CREATE INDEX IF NOT EXISTS idx_medications_active ON medications(active);
CREATE INDEX IF NOT EXISTS idx_health_records_patient ON health_records(patient_code_hash);
CREATE INDEX IF NOT EXISTS idx_health_records_type ON health_records(record_type);
CREATE INDEX IF NOT EXISTS idx_caregiver_connections_caregiver ON caregiver_connections(caregiver_id);
CREATE INDEX IF NOT EXISTS idx_caregiver_connections_patient ON caregiver_connections(patient_code_hash);
CREATE INDEX IF NOT EXISTS idx_conversations_patient ON conversations(patient_code_hash);
CREATE INDEX IF NOT EXISTS idx_paper_chunks_fts ON paper_chunks USING GIN(chunk_fts);

-- Verify tables were created
\dt
