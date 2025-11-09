-- Drop the other databases (keep only 'postgres')
-- Replace 'loveuad' and 'research' with actual database names if different

DROP DATABASE IF EXISTS loveuad;
DROP DATABASE IF EXISTS research;

-- Verify only postgres remains
SELECT datname FROM pg_database WHERE datistemplate = false;
