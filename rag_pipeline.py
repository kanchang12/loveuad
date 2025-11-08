import vertexai
from vertexai.generative_models import GenerativeModel
# The following imports are no longer needed since we removed the embedding code:
# from vertexai.language_models import TextEmbeddingModel 
# import os
# import openai
from config import Config
import logging


logger = logging.getLogger(__name__)

class RAGPipeline:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        
        # Initialize Vertex AI
        vertexai.init(project=Config.PROJECT_ID, location=Config.LOCATION)
        
        # Initialize Gemini model
        self.llm_model = GenerativeModel(Config.LLM_MODEL)
        
        logger.info("RAG Pipeline initialized with Full-Text Search (FTS)")
    
    # The generate_embedding method was correctly removed
    
    def retrieve_context(self, query):
        """Retrieve relevant context from research papers using FTS"""
        try:
            # Pass the raw user query directly to the database manager.
            # The database manager will use plainto_tsquery for robust FTS.
            results = self.db_manager.fts_search(query, top_k=Config.TOP_K_RESULTS)
            
            return results
        except Exception as e:
            logger.error(f"Context retrieval error: {e}")
            raise
    
    def build_prompt(self, query, context_chunks):
        """Build the final prompt for the LLM"""
        context_list = []
        for i, chunk in enumerate(context_chunks):
            # chunk is a dictionary returned by RealDictCursor
            source_info = f"Source {i+1}: Title: {chunk['title']}, Authors: {chunk['authors']}, Year: {chunk['year']}"
            context_list.append(f"--- Chunk {i+1} ---\n{chunk['chunk_text']}\n{source_info}\n")
            
        context_text = "\n\n".join(context_list)
        
        prompt = f"""
        You are an expert AI medical assistant specialized in dementia care. Your goal is to provide accurate, evidence-based, and compassionate answers based *only* on the provided research context.

        CONTEXT:
        {context_text}

        ---
        
        INSTRUCTIONS:
        1. Read the CONTEXT carefully.
        2. Answer the user's QUERY only using the information available in the CONTEXT.
        3. If the context does not contain relevant information, state clearly: "I cannot find a research-based answer to that question in my current index." Do not try to guess or use external knowledge.
        4. Be concise and professional.
        5. For every statement you make, cite the corresponding source number (e.g., [Source 1], [Source 2, 3]).

        QUERY: "{query}"
        """
        return prompt

    def format_sources(self, context_chunks):
        """Format unique source information for the API response"""
        unique_sources = {}
        for chunk in context_chunks:
            doi = chunk['doi']
            if doi not in unique_sources:
                unique_sources[doi] = {
                    'title': chunk['title'],
                    'authors': chunk['authors'],
                    'journal': chunk['journal'],
                    'year': chunk['year'],
                    'doi': doi
                }
        
        return list(unique_sources.values())

    def generate_response(self, prompt):
        """Call the LLM to generate the final response"""
        try:
            response = self.llm_model.generate_content(
                prompt,
                generation_config={
                    'temperature': Config.TEMPERATURE,
                    'max_output_tokens': Config.MAX_OUTPUT_TOKENS,
                }
            )
            
            return response.text
        except Exception as e:
            logger.error(f"Response generation error: {e}")
            raise
    
    def get_response(self, query):
        """Main RAG pipeline: retrieve context and generate response"""
        try:
            # Retrieve relevant research chunks
            context_chunks = self.retrieve_context(query)
            
            if not context_chunks:
                return {
                    'answer': "I cannot find a research-based answer to that question in my current index.",
                    'sources': []
                }
            
            # Build prompt with context
            prompt = self.build_prompt(query, context_chunks)
            
            # Generate response
            answer = self.generate_response(prompt)
            
            # Format sources
            sources = self.format_sources(context_chunks)
            
            return {
                'answer': answer,
                'sources': sources
            }
        
        except Exception as e:
            logger.error(f"RAG pipeline error: {e}")
            raise
