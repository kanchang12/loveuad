"""
Quick script to create analytics tables in Cloud Run database
Run this once to set up the survey and DAU tracking tables
"""

import psycopg2
from urllib.parse import urlparse
import os

# Your Cloud Run database URL
DATABASE_URL = os.environ.get('DATABASE_URL', 
    'postgresql://postgres:loveuad2024@34.147.3.18:5432/postgres')

def create_tables():
    """Create analytics tables if they don't exist"""
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    print("Creating analytics tables...")
    
    # Create survey_responses table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS survey_responses (
            id SERIAL PRIMARY KEY,
            code_hash VARCHAR(64) NOT NULL,
            completion_date DATE NOT NULL DEFAULT CURRENT_DATE,
            result_bucket VARCHAR(10) NOT NULL CHECK (result_bucket IN ('Low', 'Medium', 'High')),
            survey_day INTEGER NOT NULL CHECK (survey_day IN (30, 60, 90)),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(code_hash, survey_day)
        );
    """)
    print("✓ survey_responses table created")
    
    # Create indexes for survey_responses
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_survey_completion_date 
        ON survey_responses(completion_date);
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_survey_result_bucket 
        ON survey_responses(result_bucket);
    """)
    print("✓ survey_responses indexes created")
    
    # Create daily_active_users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_active_users (
            id SERIAL PRIMARY KEY,
            event_date DATE NOT NULL,
            event_hour INTEGER NOT NULL CHECK (event_hour >= 0 AND event_hour < 24),
            launch_count INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(event_date, event_hour)
        );
    """)
    print("✓ daily_active_users table created")
    
    # Create indexes for daily_active_users
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_dau_event_date 
        ON daily_active_users(event_date);
    """)
    print("✓ daily_active_users indexes created")
    
    # Create daily_launch_tracker table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_launch_tracker (
            id SERIAL PRIMARY KEY,
            code_hash VARCHAR(64) NOT NULL,
            launch_date DATE NOT NULL DEFAULT CURRENT_DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(code_hash, launch_date)
        );
    """)
    print("✓ daily_launch_tracker table created")
    
    # Create index for daily_launch_tracker
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_tracker_launch_date 
        ON daily_launch_tracker(launch_date);
    """)
    print("✓ daily_launch_tracker indexes created")
    
    conn.commit()
    cur.close()
    conn.close()
    
    print("\n✅ All analytics tables created successfully!")
    print("\nTables created:")
    print("  - survey_responses (stores anonymous survey completions)")
    print("  - daily_active_users (aggregated DAU counts)")
    print("  - daily_launch_tracker (temporary uniqueness check)")

if __name__ == '__main__':
    try:
        create_tables()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nMake sure your DATABASE_URL environment variable is set correctly")
