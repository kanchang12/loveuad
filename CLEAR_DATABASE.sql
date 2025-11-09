-- ============================================================
-- CLEAR ALL PATIENT DATA FROM DATABASE
-- Run this in Google Cloud SQL Console
-- ============================================================
-- This will delete ALL patient records to start fresh
-- with the new 17-character format (XXXX-XXXX-XXXX-XXXX-X)
-- ============================================================

-- Delete in order (respecting foreign keys)
DELETE FROM conversations;
DELETE FROM health_records;
DELETE FROM medications;
DELETE FROM patients;

-- Verify deletion
SELECT 'Patients:' as table_name, COUNT(*) as count FROM patients
UNION ALL
SELECT 'Medications:', COUNT(*) FROM medications
UNION ALL
SELECT 'Health Records:', COUNT(*) FROM health_records
UNION ALL
SELECT 'Conversations:', COUNT(*) FROM conversations;

-- ============================================================
-- After running this:
-- 1. All patient data is deleted
-- 2. You can register new patients with 17-character codes
-- 3. Format: XXXX-XXXX-XXXX-XXXX-X
-- ============================================================
