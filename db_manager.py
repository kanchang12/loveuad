# db_manager.py - REPLACE ENTIRE FILE

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
import logging
import os
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        """Initialize connection pool instead of single connection"""
        self.connection_pool = None
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Create connection pool with automatic reconnection"""
        try:
            self.connection_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,  # Adjust based on your needs
                host=os.environ.get('DB_HOST'),
                database=os.environ.get('DB_NAME'),
                user=os.environ.get('DB_USER'),
                password=os.environ.get('DB_PASSWORD'),
                port=os.environ.get('DB_PORT', 5432),
                cursor_factory=RealDictCursor,
                # Critical: Set connection timeout and keepalive
                connect_timeout=10,
                options='-c statement_timeout=30000'  # 30 second query timeout
            )
            logger.info("✓ Database connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to create connection pool: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """
        Context manager for database connections with automatic cleanup
        Usage: 
            with db_manager.get_connection() as conn:
                cur = conn.cursor()
                cur.execute(...)
        """
        conn = None
        try:
            # Get connection from pool
            conn = self.connection_pool.getconn()
            
            # Test if connection is still alive
            conn.isolation_level  # This will fail if connection is dead
            
            yield conn
            
        except psycopg2.InterfaceError as e:
            # Connection is dead - try to reconnect
            logger.warning(f"Dead connection detected, reconnecting: {e}")
            if conn:
                try:
                    self.connection_pool.putconn(conn, close=True)
                except:
                    pass
            
            # Reinitialize pool
            self._initialize_pool()
            
            # Get fresh connection
            conn = self.connection_pool.getconn()
            yield conn
            
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
            
        finally:
            if conn:
                try:
                    conn.commit()
                    self.connection_pool.putconn(conn)
                except Exception as e:
                    logger.error(f"Error returning connection to pool: {e}")
                    try:
                        self.connection_pool.putconn(conn, close=True)
                    except:
                        pass
    
    def insert_patient_data(self, code_hash, encrypted_data, phone_number):
        """Insert patient with proper connection handling"""
        try:
            with self.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO patients (code_hash, encrypted_data, phone_number, created_at)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                """, (code_hash, encrypted_data, phone_number))
                logger.info(f"✓ Patient registered: {code_hash[:8]}...")
        except Exception as e:
            logger.error(f"Error inserting patient data: {e}")
            raise
    
    def get_patient_data(self, code_hash):
        """Get patient data with proper connection handling"""
        try:
            with self.get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT * FROM patients WHERE code_hash = %s",
                    (code_hash,)
                )
                return cur.fetchone()
        except Exception as e:
            logger.error(f"Error fetching patient data: {e}")
            raise
    
    def insert_medication(self, code_hash, encrypted_data):
        """Insert medication"""
        try:
            with self.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO medications (code_hash, encrypted_data, active)
                    VALUES (%s, %s, true)
                """, (code_hash, encrypted_data))
        except Exception as e:
            logger.error(f"Error inserting medication: {e}")
            raise
    
    def get_medications(self, code_hash):
        """Get all medications for patient"""
        try:
            with self.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT * FROM medications 
                    WHERE code_hash = %s AND active = true
                """, (code_hash,))
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Error fetching medications: {e}")
            raise
    
    def insert_health_record(self, code_hash, record_type, encrypted_metadata, record_date=None):
        """Insert health record"""
        try:
            with self.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO health_records (code_hash, record_type, encrypted_metadata, record_date)
                    VALUES (%s, %s, %s, %s)
                """, (code_hash, record_type, encrypted_metadata, record_date))
        except Exception as e:
            logger.error(f"Error inserting health record: {e}")
            raise
    
    def get_health_records(self, code_hash):
        """Get health records"""
        try:
            with self.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT * FROM health_records 
                    WHERE code_hash = %s 
                    ORDER BY created_at DESC
                """, (code_hash,))
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Error fetching health records: {e}")
            raise
    
    def insert_conversation(self, code_hash, encrypted_query, encrypted_response, sources):
        """Insert conversation"""
        try:
            with self.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO dementia_conversations (code_hash, encrypted_query, encrypted_response, sources)
                    VALUES (%s, %s, %s, %s)
                """, (code_hash, encrypted_query, encrypted_response, sources))
        except Exception as e:
            logger.error(f"Error inserting conversation: {e}")
            raise
    
    def get_conversations(self, code_hash):
        """Get conversations"""
        try:
            with self.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT * FROM dementia_conversations 
                    WHERE code_hash = %s 
                    ORDER BY created_at DESC 
                    LIMIT 50
                """, (code_hash,))
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Error fetching conversations: {e}")
            raise
    
    def get_stats(self):
        """Get database statistics"""
        try:
            with self.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) as count FROM research_papers")
                papers = cur.fetchone()['count']
                
                cur.execute("SELECT COUNT(*) as count FROM paper_chunks")
                chunks = cur.fetchone()['count']
                
                return {
                    'total_papers': papers,
                    'total_chunks': chunks
                }
        except Exception as e:
            logger.error(f"Error fetching stats: {e}")
            return {'total_papers': 0, 'total_chunks': 0}
    
    def close_all_connections(self):
        """Close all connections in pool (call on app shutdown)"""
        if self.connection_pool:
            self.connection_pool.closeall()
            logger.info("✓ All database connections closed")
