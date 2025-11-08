import logging
import google.generativeai as genai
from config import Config

logger = logging.getLogger(__name__)

class RAGPipeline:
    """RAG Pipeline using PostgreSQL Full-Text Search and Gemini"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        
        # Initialize Gemini API
        genai.configure(api_key=Config.GEMINI_API_KEY)
        self.llm = genai.GenerativeModel(Config.LLM_MODEL)
        
        logger.info("RAG Pipeline initialized with FTS and Gemini")
    
    def format_tsquery(self, query):
        """Convert user query to tsquery format"""
        # Remove special characters and convert to lowercase
        query = query.lower()
        
        # Split into words
        words = query.split()
        
        # Filter out common stop words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could', 'may', 'might', 'can'}
        
        meaningful_words = [w for w in words if w not in stop_words and len(w) > 2]
        
        # Join with & for AND search
        if len(meaningful_words) == 0:
            # Fallback to original query
            return ' & '.join(words)
        
        return ' & '.join(meaningful_words)
    
    def search_research(self, query, top_k=Config.TOP_K_RESULTS):
        """Search research papers using Full-Text Search"""
        try:
            # Convert query to tsquery format
            tsquery_string = self.format_tsquery(query)
            
            logger.info(f"Searching with tsquery: {tsquery_string}")
            
            # Perform FTS search
            results = self.db.fts_search(tsquery_string, top_k=top_k)
            
            logger.info(f"Found {len(results)} relevant papers")
            
            return results
        
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []
    
    def build_context(self, search_results):
        """Build context from search results"""
        if not search_results:
            return None
        
        context_parts = []
        sources = []
        
        for idx, result in enumerate(search_results, 1):
            # Build context chunk
            chunk_text = result['chunk_text']
            title = result['title']
            authors = result.get('authors', 'Unknown')
            year = result.get('year', 'N/A')
            journal = result.get('journal', 'Unknown Journal')
            doi = result.get('doi', '')
            
            context_parts.append(
                f"[Source {idx}]\n"
                f"Title: {title}\n"
                f"Authors: {authors}\n"
                f"Journal: {journal} ({year})\n"
                f"Content: {chunk_text}\n"
            )
            
            # Build source citation
            source = {
                'index': idx,
                'title': title,
                'authors': authors,
                'journal': journal,
                'year': year,
                'doi': doi,
                'relevance': float(result.get('similarity', 0))
            }
            sources.append(source)
        
        context = "\n\n".join(context_parts)
        return context, sources
    
    def generate_response(self, query, context, sources):
        """Generate response using Gemini with context"""
        
        prompt = f"""You are a dementia care advisor helping caregivers with evidence-based guidance. 
You have access to peer-reviewed research papers about dementia care.

User Question: {query}

Research Context:
{context}

Instructions:
1. Provide practical, compassionate guidance based ONLY on the research context provided
2. Cite specific sources using [Source X] notation
3. Be clear about what stage of dementia (mild/moderate/severe) your advice applies to
4. Include specific, actionable steps
5. If the research doesn't fully answer the question, acknowledge this
6. Keep the response concise but comprehensive (2-3 paragraphs)
7. End with a reminder to consult healthcare professionals

Response:"""

        try:
            # Generate with Gemini
            response = self.llm.generate_content(
                prompt,
                generation_config={
                    'temperature': Config.TEMPERATURE,
                    'max_output_tokens': Config.MAX_OUTPUT_TOKENS
                }
            )
            
            answer = response.text
            
            return {
                'answer': answer,
                'sources': sources
            }
        
        except Exception as e:
            logger.error(f"Generation error: {e}")
            return {
                'answer': "I'm sorry, I encountered an error generating the response. Please try again.",
                'sources': sources
            }
    
    def get_response(self, query):
        """Main RAG pipeline: search → retrieve → generate"""
        try:
            # Step 1: Search research papers
            search_results = self.search_research(query)
            
            if not search_results:
                return {
                    'answer': "I couldn't find relevant research papers for your query. Please try rephrasing your question or ask about common dementia care topics like:\n\n• Communication strategies\n• Behavioral management\n• Daily care routines\n• Medication management\n• Safety concerns\n• Activities and engagement",
                    'sources': []
                }
            
            # Step 2: Build context
            context, sources = self.build_context(search_results)
            
            # Step 3: Generate response
            response = self.generate_response(query, context, sources)
            
            return response
        
        except Exception as e:
            logger.error(f"RAG pipeline error: {e}")
            return {
                'answer': "I'm sorry, I encountered an error processing your request. Please try again.",
                'sources': []
            }
