import psycopg2
from psycopg2.extras import RealDictCursor
import logging
import os

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.conn = None
    
    def connect(self):
        """Connect to database only when needed"""
        if self.conn is not None:
            return self.conn
            
        try:
            database_url = os.getenv('DATABASE_URL')
            if database_url:
                self.conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
            else:
                raise Exception("DATABASE_URL not set")
            logger.info("Database connected successfully")
            return self.conn
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise
    
    def get_patient_data(self, code_hash):
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM patients WHERE code_hash = %s;", (code_hash,))
            return cur.fetchone()
    
    def insert_patient_data(self, code_hash, encrypted_data):
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO patients (code_hash, encrypted_data)
                VALUES (%s, %s);
            """, (code_hash, encrypted_data))
            conn.commit()
    
    def get_medications(self, code_hash):
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM medications 
                WHERE patient_code_hash = %s AND active = TRUE;
            """, (code_hash,))
            return cur.fetchall()
    
    def insert_medication(self, code_hash, encrypted_data):
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO medications (patient_code_hash, encrypted_data)
                VALUES (%s, %s);
            """, (code_hash, encrypted_data))
            conn.commit()
    
    def get_health_records(self, code_hash):
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM health_records 
                WHERE patient_code_hash = %s 
                ORDER BY created_at DESC;
            """, (code_hash,))
            return cur.fetchall()
    
    def insert_health_record(self, code_hash, record_type, encrypted_metadata, record_date=None):
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO health_records (patient_code_hash, record_type, encrypted_metadata, record_date)
                VALUES (%s, %s, %s, %s);
            """, (code_hash, record_type, encrypted_metadata, record_date))
            conn.commit()
    
    def get_conversations(self, code_hash):
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM conversations 
                WHERE patient_code_hash = %s 
                ORDER BY created_at DESC;
            """, (code_hash,))
            return cur.fetchall()
    
    def insert_conversation(self, code_hash, encrypted_query, encrypted_response, sources):
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO conversations (patient_code_hash, encrypted_query, encrypted_response, sources)
                VALUES (%s, %s, %s, %s);
            """, (code_hash, encrypted_query, encrypted_response, sources))
            conn.commit()
    
    def get_stats(self):
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as total_papers FROM research_papers;")
            papers = cur.fetchone()['total_papers']
            cur.execute("SELECT COUNT(*) as total_chunks FROM research_chunks;")
            chunks = cur.fetchone()['total_chunks']
            return {'total_papers': papers, 'total_chunks': chunks}
