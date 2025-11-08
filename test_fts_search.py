"""
Test script for Full-Text Search functionality
"""

import os
import sys
sys.path.append('/home/claude')

from db_manager import DatabaseManager
from rag_pipeline import RAGPipeline

def test_fts_search():
    """Test Full-Text Search"""
    
    print("="*60)
    print("Testing LoveUAD FTS Search")
    print("="*60)
    
    # Initialize
    db = DatabaseManager()
    rag = RAGPipeline(db)
    
    # Get stats
    stats = db.get_stats()
    print(f"\n✓ Database Statistics:")
    print(f"  • Total Papers: {stats['total_papers']}")
    print(f"  • Total Chunks: {stats['total_chunks']}")
    
    if stats['total_papers'] == 0:
        print("\n⚠️  No papers in database!")
        print("Run: python ingest_research_fts.py <path_to_jsonl>")
        return
    
    # Test queries
    test_queries = [
        "How to communicate with dementia patients?",
        "Managing aggressive behavior in Alzheimer's",
        "Memory loss coping strategies",
        "Medication management for dementia",
        "Safety concerns at home"
    ]
    
    print(f"\n{'='*60}")
    print("Testing Sample Queries:")
    print("="*60)
    
    for query in test_queries:
        print(f"\n🔍 Query: {query}")
        print("-"*60)
        
        # Test FTS search
        tsquery = rag.format_tsquery(query)
        print(f"TSQuery: {tsquery}")
        
        results = db.fts_search(tsquery, top_k=3)
        
        if results:
            print(f"✓ Found {len(results)} results")
            for idx, result in enumerate(results, 1):
                print(f"\n[{idx}] {result['title']}")
                print(f"    Relevance: {result.get('similarity', 0):.4f}")
                print(f"    Journal: {result.get('journal', 'N/A')} ({result.get('year', 'N/A')})")
        else:
            print("✗ No results found")
    
    # Test full RAG pipeline
    print(f"\n{'='*60}")
    print("Testing Full RAG Pipeline:")
    print("="*60)
    
    test_question = "What are the best communication strategies for late-stage dementia?"
    print(f"\n❓ Question: {test_question}")
    print("-"*60)
    
    response = rag.get_response(test_question)
    
    print(f"\n💬 Answer:")
    print(response['answer'])
    
    if response['sources']:
        print(f"\n📚 Sources:")
        for source in response['sources']:
            print(f"  [{source['index']}] {source['title']}")
            print(f"      {source['authors']} - {source['journal']} ({source['year']})")
    
    print(f"\n{'='*60}")
    print("Testing Complete!")
    print("="*60)

if __name__ == "__main__":
    test_fts_search()
