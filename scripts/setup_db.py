#!/usr/bin/env python3
"""
Database setup script
Initializes both user and research database schemas
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_manager import DatabaseManager
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """Setup database schemas"""
    try:
        logger.info("Connecting to database...")
        db = DatabaseManager()
        
        logger.info("Creating user database schema...")
        db.setup_user_schema()
        
        logger.info("Creating research database schema...")
        db.setup_research_schema()
        
        logger.info("Database setup completed successfully")
        
        db.close()
        
    except Exception as e:
        logger.error(f"Database setup failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
