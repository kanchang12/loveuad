#!/usr/bin/env python3
"""
Research paper ingestion script
Loads research papers from JSON, chunks text, generates embeddings, and stores in database
"""

import sys
import time
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import logging
from tqdm import tqdm
import tiktoken
from db_manager import DatabaseManager
from rag_pipeline import RAGPipeline
from config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ResearchIngester:
    def __init__(self, db_manager):
        self.db = db_manager
        self.rag = RAGPipeline(db_manager)
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
    
    def count_tokens(self, text):
        """Count tokens in text"""
        return len(self.tokenizer.encode(text))
    
    def chunk_text(self, text, chunk_size=1000, overlap=100):
        """Chunk text into smaller pieces with overlap"""
        tokens = self.tokenizer.encode(text)
        chunks = []
        
        for i in range(0, len(tokens), chunk_size - overlap):
            chunk_tokens = tokens[i:i + chunk_size]
            chunk_text = self.tokenizer.decode(chunk_tokens)
            chunks.append(chunk_text)
        
        return chunks
    
    def process_paper(self, paper):
        """Process a single research paper"""
        try:
            # Extract metadata
            title = paper.get('title', 'Unknown')
            authors = paper.get('authors', 'Unknown')
            journal = paper.get('journal', 'Unknown')
            year = paper.get('year')
            doi = paper.get('doi', '')
            abstract = paper.get('abstract', '')
            full_text = paper.get('full_text', '')
            
            # Insert paper into database
            with self.db.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO research_papers 
                    (title, authors, journal, year, doi, abstract, full_text)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, (title, authors, journal, year, doi, abstract, full_text))
                paper_id = cur.fetchone()['id']
                self.db.conn.commit()
            
            # Chunk the paper
            # Priority 1: Abstract + conclusion together
            combined_text = f"{title}\n\n{abstract}"
            if full_text:
                # Try to extract conclusion
                lower_text = full_text.lower()
                if 'conclusion' in lower_text:
                    conclusion_idx = lower_text.rfind('conclusion')
                    conclusion = full_text[conclusion_idx:conclusion_idx+1500]
                    combined_text += f"\n\n{conclusion}"
            
            chunks = [combined_text]
            
            # Priority 2: Full text chunks
            if full_text and len(full_text) > 2000:
                text_chunks = self.chunk_text(full_text, chunk_size=Config.CHUNK_SIZE, overlap=100)
                chunks.extend(text_chunks[:10])  # Limit to 10 chunks per paper
            
            # Generate embeddings and store chunks
            for idx, chunk in enumerate(chunks):
                if len(chunk.strip()) < 100:  # Skip very short chunks
                    continue
                
                # Generate embedding
                embedding = self.rag.generate_embedding(chunk)
                
                
                
                # Store chunk
                with self.db.conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO paper_chunks 
                        (paper_id, chunk_text, chunk_index, embedding)
                        VALUES (%s, %s, %s, %s);
                    """, (paper_id, chunk, idx, embedding))
                    self.db.conn.commit()
            
            return True
        
        except Exception as e:
            logger.error(f"Error processing paper '{title}': {e}")
            return False
    
    def ingest_from_json(self, json_file_path, batch_size=100):
        """Ingest research papers from JSON file"""
        logger.info(f"Loading JSON file: {json_file_path}")
        
        # Load JSONL format (one JSON per line)
        papers = []
        with open(json_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    papers.append(json.loads(line))
        
        logger.info(f"Found {len(papers)} papers to process")
        
        successful = 0
        failed = 0
        
        for i in tqdm(range(0, len(papers), batch_size), desc="Processing papers"):
            batch = papers[i:i+batch_size]
            
            for paper in batch:
                if self.process_paper(paper):
                    successful += 1
                else:
                    failed += 1
            
            # Log progress
            if (i // batch_size + 1) % 10 == 0:
                logger.info(f"Processed {successful + failed} papers ({successful} successful, {failed} failed)")
        
        logger.info(f"Ingestion complete: {successful} successful, {failed} failed")
        
        # Final stats
        stats = self.db.get_stats()
        logger.info(f"Database now contains:")
        logger.info(f"  - {stats['total_papers']} research papers")
        logger.info(f"  - {stats['total_chunks']} indexed chunks")

def main():
    """Main ingestion function"""
    if len(sys.argv) < 2:
        print("Usage: python ingest_research.py <path_to_json_file>")
        sys.exit(1)
    
    json_file = sys.argv[1]
    
    if not os.path.exists(json_file):
        print(f"Error: File not found: {json_file}")
        sys.exit(1)
    
    try:
        logger.info("Connecting to database...")
        db = DatabaseManager()
        
        logger.info("Initializing ingester...")
        ingester = ResearchIngester(db)
        
        logger.info("Starting ingestion...")
        ingester.ingest_from_json(json_file)
        
        logger.info("Ingestion completed successfully")
        
        db.close()
        
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
