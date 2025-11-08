"""
Research Paper Ingestion Script for LoveUAD
Uses PostgreSQL Full-Text Search (no embeddings needed)
"""

import json
import psycopg2
from psycopg2.extras import RealDictCursor
from tqdm import tqdm
import logging
import sys
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def connect_to_db():
    """Connect to database"""
    try:
        # Check environment
        if os.getenv('ENVIRONMENT') == 'local':
            # Local via Cloud SQL Proxy
            conn = psycopg2.connect(
                host="127.0.0.1",
                port=5432,
                dbname="loveuad",
                user="postgres",
                password=os.getenv('DB_PASSWORD', 'LoveUAD2025SecurePass'),
                cursor_factory=RealDictCursor
            )
        else:
            # Cloud Run
            instance_connection_name = os.getenv('INSTANCE_CONNECTION_NAME')
            conn = psycopg2.connect(
                dbname="loveuad",
                user="postgres",
                password=os.getenv('DB_PASSWORD'),
                host=f"/cloudsql/{instance_connection_name}",
                cursor_factory=RealDictCursor
            )
        
        logger.info("✓ Database connected")
        return conn
    
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise

def setup_schema(conn):
    """Create tables if they don't exist"""
    with conn.cursor() as cur:
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
        
        # Paper chunks with FTS
        cur.execute("""
            CREATE TABLE IF NOT EXISTS paper_chunks (
                id SERIAL PRIMARY KEY,
                paper_id INTEGER REFERENCES research_papers(id) ON DELETE CASCADE,
                chunk_text TEXT NOT NULL,
                chunk_index INTEGER,
                chunk_fts TSVECTOR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # GIN index for FTS
        cur.execute("""
            CREATE INDEX IF NOT EXISTS paper_chunks_fts_idx 
            ON paper_chunks 
            USING GIN (chunk_fts);
        """)
        
        conn.commit()
        logger.info("✓ Database schema ready")

def chunk_text(text, max_length=1000):
    """Split text into chunks of approximately max_length characters"""
    if not text or len(text) <= max_length:
        return [text]
    
    chunks = []
    sentences = text.split('. ')
    current_chunk = ""
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) < max_length:
            current_chunk += sentence + ". "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + ". "
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks if chunks else [text]

def insert_paper(conn, paper):
    """Insert paper and its chunks with FTS"""
    try:
        with conn.cursor() as cur:
            # Insert paper metadata
            cur.execute("""
                INSERT INTO research_papers (title, authors, journal, year, doi, abstract, full_text)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                paper.get('title', '')[:500],
                paper.get('authors', '')[:500],
                paper.get('journal', '')[:200],
                paper.get('year'),
                paper.get('doi', '')[:100],
                paper.get('abstract', ''),
                paper.get('full_text', '')
            ))
            
            paper_id = cur.fetchone()['id']
            
            # Create chunks from abstract and full_text
            abstract = paper.get('abstract', '')
            full_text = paper.get('full_text', '')
            title = paper.get('title', '')
            
            # Combine title + abstract for first chunk (most important)
            first_chunk = f"{title}\n\n{abstract}"
            
            # Insert first chunk with FTS
            cur.execute("""
                INSERT INTO paper_chunks (paper_id, chunk_text, chunk_index, chunk_fts)
                VALUES (%s, %s, %s, to_tsvector('english', %s));
            """, (paper_id, first_chunk, 0, first_chunk))
            
            # Chunk the full text if available
            if full_text and len(full_text) > 100:
                text_chunks = chunk_text(full_text, max_length=1000)
                
                for idx, chunk in enumerate(text_chunks, start=1):
                    cur.execute("""
                        INSERT INTO paper_chunks (paper_id, chunk_text, chunk_index, chunk_fts)
                        VALUES (%s, %s, %s, to_tsvector('english', %s));
                    """, (paper_id, chunk, idx, chunk))
            
            conn.commit()
            return paper_id
    
    except Exception as e:
        conn.rollback()
        logger.error(f"Error inserting paper '{paper.get('title', 'Unknown')}': {e}")
        return None

def ingest_papers(conn, jsonl_path):
    """Load and ingest papers from JSONL file"""
    
    # Check if file exists
    if not os.path.exists(jsonl_path):
        logger.error(f"File not found: {jsonl_path}")
        sys.exit(1)
    
    # Read papers
    logger.info(f"Reading papers from: {jsonl_path}")
    papers = []
    
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                papers.append(json.loads(line))
    
    logger.info(f"Found {len(papers)} papers to ingest")
    
    # Check if papers already exist
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM research_papers;")
        existing_count = cur.fetchone()['count']
    
    if existing_count > 0:
        logger.warning(f"Database already has {existing_count} papers!")
        response = input("Do you want to continue and add more papers? (yes/no): ")
        if response.lower() != 'yes':
            logger.info("Ingestion cancelled")
            return
    
    # Ingest papers with progress bar
    successful = 0
    failed = 0
    
    logger.info("Starting ingestion...")
    
    for paper in tqdm(papers, desc="Ingesting papers"):
        result = insert_paper(conn, paper)
        if result:
            successful += 1
        else:
            failed += 1
    
    logger.info("="*60)
    logger.info(f"Ingestion complete!")
    logger.info(f"✓ Successful: {successful}")
    logger.info(f"✗ Failed: {failed}")
    logger.info("="*60)
    
    # Get final stats
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) as total_papers FROM research_papers;")
        total_papers = cur.fetchone()['total_papers']
        
        cur.execute("SELECT COUNT(*) as total_chunks FROM paper_chunks;")
        total_chunks = cur.fetchone()['total_chunks']
    
    logger.info(f"Database now contains:")
    logger.info(f"  • {total_papers} research papers")
    logger.info(f"  • {total_chunks} indexed chunks")
    logger.info("="*60)

def main():
    """Main ingestion process"""
    if len(sys.argv) < 2:
        print("Usage: python ingest_research_fts.py <path_to_jsonl_file>")
        print("Example: python ingest_research_fts.py ~/loveUAD_Cleaned_Research_Papers.jsonl")
        sys.exit(1)
    
    jsonl_path = sys.argv[1]
    
    logger.info("="*60)
    logger.info("LoveUAD Research Paper Ingestion (FTS)")
    logger.info("="*60)
    
    # Connect to database
    conn = connect_to_db()
    
    # Setup schema
    setup_schema(conn)
    
    # Ingest papers
    ingest_papers(conn, jsonl_path)
    
    # Close connection
    conn.close()
    logger.info("Database connection closed")

if __name__ == "__main__":
    main()
