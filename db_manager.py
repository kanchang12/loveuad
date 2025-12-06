# db_manager.py - COMPLETE FILE WITH STATUS METHODS

import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import logging
import os

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.conn = None
        self.connect()
    
    def connect(self):
        """Connect with auto-reconnect if dead"""
        if self.conn is not None:
            try:
                with self.conn.cursor() as cur:
                    cur.execute("SELECT 1")
                return self.conn
            except:
                logger.warning("🔄 Reconnecting to database...")
                try:
                    self.conn.close()
                except:
                    pass
                self.conn = None
        
        try:
            database_url = os.getenv('DATABASE_URL')
            if not database_url:
                raise Exception("DATABASE_URL not set")
            self.conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
            self.conn.autocommit = False
            logger.info("✓ Database connected")
            return self.conn
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """Context manager that ensures connection is alive"""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Transaction error: {e}")
            raise
    
    def get_patient_data(self, code_hash):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM patients WHERE code_hash = %s;", (code_hash,))
                result = cur.fetchone()
                conn.commit()
                return result
        except Exception as e:
            logger.error(f"Error fetching patient: {e}")
            conn.rollback()
            raise
    
    def insert_patient_data(self, code_hash, encrypted_data, phone_number=''):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO patients (code_hash, encrypted_data, phone_number)
                    VALUES (%s, %s, %s);
                """, (code_hash, encrypted_data, phone_number))
                conn.commit()
                logger.info(f"✅ Patient saved: {code_hash[:8]}...")
        except Exception as e:
            logger.error(f"❌ Error saving patient: {e}")
            conn.rollback()
            raise
    
    def get_medications(self, code_hash):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM medications 
                    WHERE code_hash = %s AND active = TRUE;
                """, (code_hash,))
                result = cur.fetchall()
                conn.commit()
                return result
        except Exception as e:
            logger.error(f"Error fetching medications: {e}")
            conn.rollback()
            raise
    
    def insert_medication(self, code_hash, encrypted_data):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO medications (code_hash, encrypted_data, active)
                    VALUES (%s, %s, true);
                """, (code_hash, encrypted_data))
                conn.commit()
                logger.info(f"✅ Medication saved")
        except Exception as e:
            logger.error(f"❌ Error saving medication: {e}")
            conn.rollback()
            raise
    
    def get_health_records(self, code_hash):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM health_records 
                    WHERE code_hash = %s 
                    ORDER BY created_at DESC;
                """, (code_hash,))
                result = cur.fetchall()
                conn.commit()
                return result
        except Exception as e:
            logger.error(f"Error fetching health records: {e}")
            conn.rollback()
            raise
    
    def insert_health_record(self, code_hash, record_type, encrypted_metadata, record_date=None):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO health_records (code_hash, record_type, encrypted_metadata, record_date)
                    VALUES (%s, %s, %s, %s);
                """, (code_hash, record_type, encrypted_metadata, record_date))
                conn.commit()
                logger.info(f"✅ Health record saved")
        except Exception as e:
            logger.error(f"❌ Error saving health record: {e}")
            conn.rollback()
            raise
    
    def get_conversations(self, code_hash):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM conversations 
                    WHERE code_hash = %s 
                    ORDER BY created_at DESC;
                """, (code_hash,))
                result = cur.fetchall()
                conn.commit()
                return result
        except Exception as e:
            logger.error(f"Error fetching conversations: {e}")
            conn.rollback()
            raise
    
    def insert_conversation(self, code_hash, encrypted_query, encrypted_response, sources):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO conversations (code_hash, encrypted_query, encrypted_response, sources)
                    VALUES (%s, %s, %s, %s);
                """, (code_hash, encrypted_query, encrypted_response, sources))
                conn.commit()
        except Exception as e:
            logger.error(f"Error inserting conversation: {e}")
            conn.rollback()
            raise
    
    def fts_search(self, tsquery_string, top_k=5):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        c.chunk_text,
                        p.title,
                        p.authors,
                        p.journal,
                        p.year,
                        p.doi,
                        ts_rank(c.chunk_fts, to_tsquery('english', %s)) as similarity
                    FROM paper_chunks c
                    JOIN research_papers p ON c.paper_id = p.id
                    WHERE c.chunk_fts @@ to_tsquery('english', %s)
                    ORDER BY similarity DESC
                    LIMIT %s;
                """, (tsquery_string, tsquery_string, top_k))
                result = cur.fetchall()
                conn.commit()
                return result
        except Exception as e:
            logger.error(f"FTS search error: {e}")
            conn.rollback()
            return []
    
    def get_stats(self):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as total_papers FROM research_papers;")
                papers = cur.fetchone()['total_papers']
                cur.execute("SELECT COUNT(*) as total_chunks FROM paper_chunks;")
                chunks = cur.fetchone()['total_chunks']
                conn.commit()
                return {'total_papers': papers, 'total_chunks': chunks}
        except Exception as e:
            logger.error(f"Error fetching stats: {e}")
            conn.rollback()
            raise
    
    def update_reminder_status(self, code_hash, medication_name, new_status):
        """Update medication reminder status"""
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE medication_reminders 
                    SET daily_status = %s
                    WHERE code_hash = %s AND medication_name = %s
                """, (new_status, code_hash, medication_name))
                conn.commit()
                logger.info(f"✅ Status: {medication_name} → {new_status}")
        except Exception as e:
            logger.error(f"❌ Status update error: {e}")
            conn.rollback()
            raise
    
    def reset_all_reminder_statuses(self):
        """Reset all to PENDING at midnight"""
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE medication_reminders SET daily_status = 'PENDING'")
                affected = cur.rowcount
                conn.commit()
                logger.info(f"✅ Reset {affected} reminders to PENDING")
                return affected
        except Exception as e:
            logger.error(f"❌ Reset error: {e}")
            conn.rollback()
            raise
