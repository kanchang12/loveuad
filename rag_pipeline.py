import vertexai
from vertexai.generative_models import GenerativeModel
from vertexai.language_models import TextEmbeddingModel
from config import Config
import logging

logger = logging.getLogger(__name__)

class RAGPipeline:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        
        # Initialize Vertex AI
        vertexai.init(project=Config.PROJECT_ID, location=Config.LOCATION)
        
        # Initialize models
        self.embedding_model = TextEmbeddingModel.from_pretrained(Config.EMBEDDING_MODEL)
        self.llm_model = GenerativeModel(Config.LLM_MODEL)
        
        logger.info("RAG Pipeline initialized")
    
    def generate_embedding(self, text):
        """Generate embedding for text"""
        try:
            embeddings = self.embedding_model.get_embeddings([text])
            return embeddings[0].values
        except Exception as e:
            logger.error(f"Embedding generation error: {e}")
            raise
    
    def retrieve_context(self, query):
        """Retrieve relevant context from research papers"""
        try:
            # Generate query embedding
            query_embedding = self.generate_embedding(query)
            
            # Vector search
            results = self.db_manager.vector_search(query_embedding, top_k=Config.TOP_K_RESULTS)
            
            return results
        except Exception as e:
            logger.error(f"Context retrieval error: {e}")
            raise
    
    def format_sources(self, results):
        """Format research paper sources"""
        sources = []
        seen_papers = set()
        
        for result in results:
            paper_key = f"{result['title']}_{result['year']}"
            if paper_key not in seen_papers:
                sources.append({
                    'title': result['title'],
                    'authors': result['authors'],
                    'journal': result['journal'],
                    'year': result['year'],
                    'doi': result['doi'],
                    'similarity': float(result['similarity'])
                })
                seen_papers.add(paper_key)
        
        return sources
    
    def build_prompt(self, query, context_chunks):
        """Build prompt with context and citation instructions"""
        
        # Build context from chunks
        context_text = "\n\n".join([
            f"Source {i+1}:\n{chunk['chunk_text']}\n(From: {chunk['title']}, {chunk['authors']}, {chunk['journal']}, {chunk['year']})"
            for i, chunk in enumerate(context_chunks)
        ])
        
        system_prompt = """You are a dementia care advisor providing guidance to family caregivers.

CRITICAL RULES:
1. Base your responses ONLY on the provided research context below
2. ALWAYS cite sources using this format: [Author et al., Year, Journal]
3. If multiple sources support a point, cite all: [Source1][Source2]
4. If the context does not contain information to answer the question, say "I don't have research evidence for this specific question"
5. Provide practical, compassionate guidance in simple language
6. Focus on evidence-based strategies

Example response format:
"Cognitive stimulation therapy has been shown to improve memory in dementia patients [Smith et al., 2023, Journal of Alzheimer's Disease]. The therapy involves structured group activities [Jones et al., 2022, Neurology]."

RESEARCH CONTEXT:
{context}

USER QUESTION:
{query}

Provide an evidence-based answer with proper citations:"""
        
        prompt = system_prompt.format(context=context_text, query=query)
        
        return prompt
    
    def generate_response(self, prompt):
        """Generate response using Gemini"""
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
                    'answer': "I don't have research evidence to answer this question. Please consult with healthcare professionals.",
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
