import psycopg2
from psycopg2.extras import RealDictCursor
from pgvector.psycopg2 import register_vector
from config import Config
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.conn = None
        self.connect()
    
    def connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(
                Config.DB_CONNECTION_STRING,
                cursor_factory=RealDictCursor
            )
            register_vector(self.conn)
            logger.info("Database connection established")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise
    
    def setup_user_schema(self):
        """Create user database tables"""
        with self.conn.cursor() as cur:
            # Patients table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS patients (
                    id SERIAL PRIMARY KEY,
                    code_hash TEXT UNIQUE NOT NULL,
                    encrypted_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Medications table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS medications (
                    id SERIAL PRIMARY KEY,
                    patient_code_hash TEXT NOT NULL,
                    encrypted_data TEXT NOT NULL,
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Health records table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS health_records (
                    id SERIAL PRIMARY KEY,
                    patient_code_hash TEXT NOT NULL,
                    record_type TEXT NOT NULL,
                    encrypted_metadata TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Caregiver connections table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS caregiver_connections (
                    id SERIAL PRIMARY KEY,
                    caregiver_id TEXT NOT NULL,
                    patient_code_hash TEXT NOT NULL,
                    patient_nickname TEXT,
                    access_granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Dementia conversations table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dementia_conversations (
                    id SERIAL PRIMARY KEY,
                    patient_code_hash TEXT NOT NULL,
                    encrypted_query TEXT NOT NULL,
                    encrypted_response TEXT NOT NULL,
                    sources JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Create indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_patients_code_hash ON patients(code_hash);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_medications_code_hash ON medications(patient_code_hash);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_health_records_code_hash ON health_records(patient_code_hash);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_dementia_code_hash ON dementia_conversations(patient_code_hash);")
            
            self.conn.commit()
            logger.info("User database schema created")
    
    def setup_research_schema(self):
        """Create research database tables for RAG"""
        with self.conn.cursor() as cur:
            # Enable pgvector extension
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            
            # Research papers table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS research_papers (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    authors TEXT,
                    journal TEXT,
                    year INTEGER,
                    doi TEXT,
                    abstract TEXT,
                    full_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Paper chunks with embeddings
            cur.execute("""
                CREATE TABLE IF NOT EXISTS paper_chunks (
                    id SERIAL PRIMARY KEY,
                    paper_id INTEGER REFERENCES research_papers(id),
                    chunk_text TEXT NOT NULL,
                    chunk_index INTEGER,
                    embedding vector(768),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Vector similarity index
            cur.execute("""
                CREATE INDEX IF NOT EXISTS paper_chunks_embedding_idx 
                ON paper_chunks 
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100);
            """)
            
            self.conn.commit()
            logger.info("Research database schema created")
    
    def vector_search(self, query_embedding, top_k=5):
        """Perform vector similarity search in research papers"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    pc.chunk_text,
                    rp.title,
                    rp.authors,
                    rp.journal,
                    rp.year,
                    rp.doi,
                    1 - (pc.embedding <=> %s::vector) AS similarity
                FROM paper_chunks pc
                JOIN research_papers rp ON pc.paper_id = rp.id
                ORDER BY pc.embedding <=> %s::vector
                LIMIT %s;
            """, (query_embedding, query_embedding, top_k))
            
            results = cur.fetchall()
            return results
    
    def get_stats(self):
        """Get database statistics"""
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as count FROM research_papers;")
            papers = cur.fetchone()
            papers_count = papers['count'] if papers else 0
            
            cur.execute("SELECT COUNT(*) as count FROM paper_chunks;")
            chunks = cur.fetchone()
            chunks_count = chunks['count'] if chunks else 0
            
            return {
                "total_papers": papers_count,
                "total_chunks": chunks_count
            }
    
    def insert_patient(self, code_hash, encrypted_data):
        """Insert new patient"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO patients (code_hash, encrypted_data)
                VALUES (%s, %s)
                RETURNING id;
            """, (code_hash, encrypted_data))
            self.conn.commit()
            return cur.fetchone()['id']
    
    def get_patient(self, code_hash):
        """Get patient by code hash"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM patients WHERE code_hash = %s;
            """, (code_hash,))
            return cur.fetchone()
    
    def insert_medication(self, code_hash, encrypted_data):
        """Insert medication"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO medications (patient_code_hash, encrypted_data)
                VALUES (%s, %s)
                RETURNING id;
            """, (code_hash, encrypted_data))
            self.conn.commit()
            return cur.fetchone()['id']
    
    def get_medications(self, code_hash):
        """Get active medications"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM medications 
                WHERE patient_code_hash = %s AND active = TRUE
                ORDER BY created_at DESC;
            """, (code_hash,))
            return cur.fetchall()
    
    def insert_health_record(self, code_hash, record_type, encrypted_metadata):
        """Insert health record"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO health_records (patient_code_hash, record_type, encrypted_metadata)
                VALUES (%s, %s, %s)
                RETURNING id;
            """, (code_hash, record_type, encrypted_metadata))
            self.conn.commit()
            return cur.fetchone()['id']
    
    def get_health_records(self, code_hash):
        """Get health records"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM health_records 
                WHERE patient_code_hash = %s
                ORDER BY created_at DESC;
            """, (code_hash,))
            return cur.fetchall()
    
    def insert_conversation(self, code_hash, encrypted_query, encrypted_response, sources):
        """Insert dementia conversation"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO dementia_conversations 
                (patient_code_hash, encrypted_query, encrypted_response, sources)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
            """, (code_hash, encrypted_query, encrypted_response, psycopg2.extras.Json(sources)))
            self.conn.commit()
            return cur.fetchone()['id']
    
    def get_conversations(self, code_hash, limit=50):
        """Get conversation history"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM dementia_conversations 
                WHERE patient_code_hash = %s
                ORDER BY created_at DESC
                LIMIT %s;
            """, (code_hash, limit))
            return cur.fetchall()
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
