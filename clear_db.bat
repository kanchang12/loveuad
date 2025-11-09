@echo off
echo ============================================================
echo CLEARING PATIENT DATA FROM CLOUD SQL
echo ============================================================
echo.
echo This will run SQL commands on your Cloud SQL database
echo to delete ALL patient data and start fresh with 17-char codes
echo.
echo Make sure you have gcloud CLI installed and authenticated!
echo.
pause

gcloud sql connect loveuad-db --user=postgres --quiet --database=loveuad

echo.
echo Once connected, paste these commands:
echo.
echo DELETE FROM conversations;
echo DELETE FROM health_records;
echo DELETE FROM medications;
echo DELETE FROM patients;
echo.
pause
