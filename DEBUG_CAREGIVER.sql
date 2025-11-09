-- Debug Caregiver Data Access Issue
-- Run this to check what data exists

-- 1. Check patients table
SELECT 'PATIENTS TABLE' as info;
SELECT code_hash, 
       encrypted_data::text as patient_info,
       created_at
FROM patients
ORDER BY created_at DESC
LIMIT 5;

-- 2. Check medications table
SELECT 'MEDICATIONS TABLE' as info;
SELECT patient_code_hash,
       encrypted_data::text as medication_info,
       active,
       created_at
FROM medications
ORDER BY created_at DESC
LIMIT 10;

-- 3. Check if medications exist for specific patient
-- (Replace 'YOUR_CODE_HASH' with actual code_hash from patients table above)
SELECT 'MEDICATIONS FOR SPECIFIC PATIENT' as info;
SELECT COUNT(*) as total_medications,
       SUM(CASE WHEN active = TRUE THEN 1 ELSE 0 END) as active_medications
FROM medications
WHERE patient_code_hash = 'YOUR_CODE_HASH_HERE';

-- 4. Check health records
SELECT 'HEALTH RECORDS TABLE' as info;
SELECT patient_code_hash,
       record_type,
       created_at
FROM health_records
ORDER BY created_at DESC
LIMIT 5;

-- 5. Check caregiver connections
SELECT 'CAREGIVER CONNECTIONS TABLE' as info;
SELECT caregiver_id,
       patient_code_hash,
       patient_nickname,
       created_at
FROM caregiver_connections
ORDER BY created_at DESC
LIMIT 5;
