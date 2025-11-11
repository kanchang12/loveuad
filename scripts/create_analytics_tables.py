#!/usr/bin/env python3
"""
Create analytics tables for survey and DAU tracking
Run this script to set up the database tables
"""

import os
import sys

# Add parent directory to path to import db_manager
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_manager import DatabaseManager

def create_tables():
    """Create survey_responses, daily_active_users, and daily_launch_tracker tables"""
    try:
        db_manager = DatabaseManager()
        cur = db_manager.conn.cursor()
        
        print("Creating analytics tables...")
        
        # Survey responses table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS survey_responses (
                id SERIAL PRIMARY KEY,
                code_hash VARCHAR(64) NOT NULL,
                completion_date DATE NOT NULL,
                result_bucket VARCHAR(20) NOT NULL CHECK (result_bucket IN ('Low', 'Medium', 'High')),
                survey_day INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(code_hash, survey_day)
            )
        """)
        print("✓ Created survey_responses table")
        
        # Indexes for survey table
        cur.execute("CREATE INDEX IF NOT EXISTS idx_survey_completion ON survey_responses(completion_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_survey_bucket ON survey_responses(result_bucket)")
        print("✓ Created survey indexes")
        
        # Daily active users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_active_users (
                id SERIAL PRIMARY KEY,
                event_date DATE NOT NULL,
                event_hour INT NOT NULL CHECK (event_hour >= 0 AND event_hour < 24),
                launch_count INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(event_date, event_hour)
            )
        """)
        print("✓ Created daily_active_users table")
        
        # Index for DAU table
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dau_date ON daily_active_users(event_date)")
        print("✓ Created DAU indexes")
        
        # Temporary launch tracker table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_launch_tracker (
                code_hash VARCHAR(64) NOT NULL,
                launch_date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(code_hash, launch_date)
            )
        """)
        print("✓ Created daily_launch_tracker table")
        
        # Index for tracker
        cur.execute("CREATE INDEX IF NOT EXISTS idx_launch_tracker_date ON daily_launch_tracker(launch_date)")
        print("✓ Created tracker indexes")
        
        # Add comments
        cur.execute("COMMENT ON TABLE survey_responses IS 'Anonymous survey responses - NO PII stored, only code hash and result bucket'")
        cur.execute("COMMENT ON TABLE daily_active_users IS 'Aggregated DAU counts - NO individual user data, only hourly totals'")
        cur.execute("COMMENT ON TABLE daily_launch_tracker IS 'Temporary launch tracking - auto-cleaned after 48 hours'")
        
        db_manager.conn.commit()
        print("\n✅ All analytics tables created successfully!")
        
        # Verify tables
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('survey_responses', 'daily_active_users', 'daily_launch_tracker')
            ORDER BY table_name
        """)
        tables = cur.fetchall()
        print(f"\nVerified tables: {[t[0] for t in tables]}")
        
        cur.close()
        db_manager.close()
        
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        sys.exit(1)

if __name__ == '__main__':
    print("=" * 60)
    print("LoveUAD Analytics Tables Setup")
    print("=" * 60)
    create_tables()
