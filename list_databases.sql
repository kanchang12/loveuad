-- List all databases in PostgreSQL
SELECT datname FROM pg_database WHERE datistemplate = false;
