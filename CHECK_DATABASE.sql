-- ============================================================
-- STEP 1: CHECK DATABASE TABLES AND DATA
-- Run this FIRST to see what exists
-- ============================================================

-- Show all tables
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public'
ORDER BY table_name;

-- Count records in each table (if they exist)
SELECT 'patients' as table_name, COUNT(*) as record_count FROM patients
UNION ALL
SELECT 'medications', COUNT(*) FROM medications
UNION ALL
SELECT 'health_records', COUNT(*) FROM health_records
UNION ALL
SELECT 'conversations', COUNT(*) FROM conversations;

-- Show structure of patients table
SELECT column_name, data_type, character_maximum_length
FROM information_schema.columns
WHERE table_name = 'patients'
ORDER BY ordinal_position;

-- Show a sample patient code hash (first 10 characters)
SELECT LEFT(code_hash, 10) as code_hash_sample, 
       LENGTH(code_hash) as hash_length,
       created_at
FROM patients
LIMIT 5;

-- ============================================================
-- After running this, you'll know:
-- 1. What tables exist
-- 2. How many records are in each
-- 3. What the patient table structure looks like
-- ============================================================
