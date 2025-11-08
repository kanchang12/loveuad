import psycopg2
from psycopg2.extras import RealDictCursor
# Removed: from pgvector.psycopg2 import register_vector
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
            # Removed: register_vector(self.conn)
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (patient_code_hash) REFERENCES patients(code_hash)
                );
            """)

            # Records table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS health_records (
                    id SERIAL PRIMARY KEY,
                    patient_code_hash TEXT NOT NULL,
                    encrypted_data TEXT NOT NULL,
                    record_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (patient_code_hash) REFERENCES patients(code_hash)
                );
            """)

            # Conversations table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dementia_conversations (
                    id SERIAL PRIMARY KEY,
                    patient_code_hash TEXT NOT NULL,
                    encrypted_query TEXT NOT NULL,
                    encrypted_response TEXT NOT NULL,
                    sources JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (patient_code_hash) REFERENCES patients(code_hash)
                );
            """)

            self.conn.commit()
            logger.info("User database schema created")

    def setup_research_schema(self):
        """Create research database tables for RAG using FTS"""
        with self.conn.cursor() as cur:
            # Research papers table (KEEP)
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
            
            # Paper chunks with FTS index (MODIFIED for FTS)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS paper_chunks (
                    id SERIAL PRIMARY KEY,
                    paper_id INTEGER REFERENCES research_papers(id),
                    chunk_text TEXT NOT NULL,
                    chunk_index INTEGER,
                    -- NEW: Column for Full-Text Search
                    chunk_fts TSVECTOR,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # NEW: GIN Index for efficient Full-Text Search
            cur.execute("""
                CREATE INDEX IF NOT EXISTS paper_chunks_fts_idx 
                ON paper_chunks 
                USING GIN (chunk_fts);
            """)
            
            self.conn.commit()
            logger.info("Research database schema created with FTS index")

    def insert_paper_chunk(self, paper_id, chunk_text, chunk_index):
        """Insert a chunk of a paper and calculate its FTS vector"""
        with self.conn.cursor() as cur:
            # The chunk_fts column is populated using to_tsvector on the chunk_text
            cur.execute("""
                INSERT INTO paper_chunks (paper_id, chunk_text, chunk_index, chunk_fts)
                VALUES (%s, %s, %s, to_tsvector('english', %s))
                RETURNING id;
            """, (paper_id, chunk_text, chunk_index, chunk_text))
            self.conn.commit()
            return cur.fetchone()['id']

    def fts_search(self, tsquery_string, top_k=Config.TOP_K_RESULTS):
        """Perform Full-Text Search in research papers"""
        # Note: tsquery_string should be pre-formatted (e.g., 'term1 & term2')
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    pc.chunk_text,
                    rp.title,
                    rp.authors,
                    rp.journal,
                    rp.year,
                    rp.doi,
                    -- Use ts_rank_cd for relevance scoring
                    ts_rank_cd(pc.chunk_fts, TO_TSQUERY('english', %s)) AS similarity
                FROM paper_chunks pc
                JOIN research_papers rp ON pc.paper_id = rp.id
                -- Match chunks where the FTS index contains the query
                WHERE pc.chunk_fts @@ TO_TSQUERY('english', %s)
                ORDER BY similarity DESC
                LIMIT %s;
            """, (tsquery_string, tsquery_string, top_k))
            
            results = cur.fetchall()
            return results

    def insert_paper_metadata(self, title, authors, journal, year, doi, abstract, full_text):
        """Insert metadata for a new research paper"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO research_papers (title, authors, journal, year, doi, abstract, full_text)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (title, authors, journal, year, doi, abstract, full_text))
            self.conn.commit()
            return cur.fetchone()['id']

    def get_stats(self):
        """Get database statistics"""
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total_papers FROM research_papers;")
            total_papers = cur.fetchone()['total_papers']
            
            cur.execute("SELECT COUNT(*) AS total_chunks FROM paper_chunks;")
            total_chunks = cur.fetchone()['total_chunks']
            
            return {
                'total_papers': total_papers,
                'total_chunks': total_chunks
            }

    def insert_patient_data(self, code_hash, encrypted_data):
        """Insert new patient with encrypted data"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO patients (code_hash, encrypted_data)
                VALUES (%s, %s)
                RETURNING id;
            """, (code_hash, encrypted_data))
            self.conn.commit()
            return cur.fetchone()['id']

    def get_patient_data(self, code_hash):
        """Get patient's encrypted data"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT encrypted_data FROM patients 
                WHERE code_hash = %s;
            """, (code_hash,))
            return cur.fetchone()

    def insert_medication(self, code_hash, encrypted_data):
        """Insert new medication record"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO medications (patient_code_hash, encrypted_data)
                VALUES (%s, %s)
                RETURNING id;
            """, (code_hash, encrypted_data))
            self.conn.commit()
            return cur.fetchone()['id']
    
    def get_medications(self, code_hash):
        """Get all medication records"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM medications 
                WHERE patient_code_hash = %s
                ORDER BY created_at DESC;
            """, (code_hash,))
            return cur.fetchall()

    def insert_health_record(self, code_hash, encrypted_data, record_date):
        """Insert a new health record"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO health_records (patient_code_hash, encrypted_data, record_date)
                VALUES (%s, %s, %s)
                RETURNING id;
            """, (code_hash, encrypted_data, record_date))
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
