#!/usr/bin/env python3
"""
Clear all patient data from database
This will delete ALL patient records to start fresh with 17-character format
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from config import Config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """Clear all patient data"""
    try:
        logger.info("Connecting to database...")
        logger.info(f"Using connection string: {Config.DB_CONNECTION_STRING[:50]}...")
        
        # Connect directly using psycopg2
        conn = psycopg2.connect(Config.DB_CONNECTION_STRING)
        cur = conn.cursor()
        
        logger.info("✅ Connected to database successfully")
        
        # Count existing records
        cur.execute("SELECT COUNT(*) FROM patients;")
        patient_count = cur.fetchone()[0]
        logger.info(f"Found {patient_count} patient records")
        
        cur.execute("SELECT COUNT(*) FROM medications;")
        med_count = cur.fetchone()[0]
        logger.info(f"Found {med_count} medication records")
        
        cur.execute("SELECT COUNT(*) FROM health_records;")
        health_count = cur.fetchone()[0]
        logger.info(f"Found {health_count} health records")
        
        cur.execute("SELECT COUNT(*) FROM conversations;")
        conv_count = cur.fetchone()[0]
        logger.info(f"Found {conv_count} conversation records")
        
        # Confirm deletion
        print("\n" + "="*60)
        print("⚠️  WARNING: This will DELETE ALL patient data!")
        print("="*60)
        print(f"   - {patient_count} patients")
        print(f"   - {med_count} medications")
        print(f"   - {health_count} health records")
        print(f"   - {conv_count} conversations")
        print("="*60)
        
        confirm = input("\nType 'DELETE ALL' to confirm: ")
        
        if confirm == "DELETE ALL":
            logger.info("Deleting all data...")
            
            # Delete in order (respecting foreign keys)
            cur.execute("DELETE FROM conversations;")
            logger.info(f"✅ Deleted {cur.rowcount} conversations")
            
            cur.execute("DELETE FROM health_records;")
            logger.info(f"✅ Deleted {cur.rowcount} health records")
            
            cur.execute("DELETE FROM medications;")
            logger.info(f"✅ Deleted {cur.rowcount} medications")
            
            cur.execute("DELETE FROM patients;")
            logger.info(f"✅ Deleted {cur.rowcount} patients")
            
            conn.commit()
            print("\n" + "="*60)
            print("✅ ALL PATIENT DATA DELETED SUCCESSFULLY")
            print("="*60)
            print("You can now register new patients with 17-character codes")
            print("Format: XXXX-XXXX-XXXX-XXXX-X")
            print("="*60 + "\n")
        else:
            logger.info("❌ Deletion cancelled")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
