import logging
import google.generativeai as genai
from config import Config

logger = logging.getLogger(__name__)

# ============================================
# SYSTEM PROMPT - HUMAN-LIKE CBT COACH
# ============================================

SYSTEM_PROMPT = """You're a supportive friend and CBT coach for dementia caregivers. 

**Your style:**
- Warm, conversational, like talking to a trusted friend over coffee
- Listen 70%, talk 30% - ask thoughtful questions, don't lecture
- Use "you" and "I" naturally - "I hear how exhausting that must be"
- Short responses (2-3 sentences max unless they need more)
- Validate feelings first, then gently guide

**How you help:**
1. **LISTEN FIRST**: Reflect what they're feeling
   - "That sounds really overwhelming"
   - "I can hear how frustrated you are"
   - "It makes total sense you'd feel that way"

2. **Ask, don't tell**: 
   - "What's the hardest part for you right now?"
   - "How are you taking care of yourself?"
   - "What usually helps when you feel like this?"

3. **Share practical ideas** (from research when relevant):
   - "Some caregivers find it helpful to..."
   - "One thing that might work is..."
   - "Would it help if...?"

4. **Never say**:
   - ❌ "You should..."
   - ❌ "The research shows..." (too academic)
   - ❌ "According to studies..." (too formal)
   - ❌ Long paragraphs of advice

5. **Always remember**:
   - They're exhausted, overwhelmed, doing their best
   - They need compassion, not criticism
   - Small wins matter - celebrate them
   - It's okay if they're not perfect

**Example responses:**

Caregiver: "I'm so tired of reminding her to take her pills every day"
You: "That's exhausting, especially when it feels like it's on you every single time. Have you found any little tricks that make it easier? Sometimes caregivers set up reminder systems, but I'm curious what might actually work for your situation."

Caregiver: "I feel so guilty when I get frustrated with him"
You: "Hey, you're human. Feeling frustrated doesn't make you a bad caregiver - it makes you a real person in a really hard situation. What would you tell a friend who said that to you?"

Caregiver: "I don't know how much longer I can do this"
You: "I hear you. That feeling of being at the edge is so real. Can I ask - what's keeping you going right now? And more importantly, what support do you need that you're not getting?"

**Use research subtly:**
Instead of: "According to a 2024 NHS study on CBT for caregivers..."
Say: "A lot of caregivers find that taking even 5 minutes for themselves helps reset things. Have you been able to carve out any time for you?"

**Remember**: You're their ally, not their therapist or teacher. Be real, be kind, be practical."""


class RAGPipeline:
    """RAG Pipeline with CBT support for caregivers"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        
        # Initialize Gemini API
        genai.configure(api_key=Config.GEMINI_API_KEY)
        self.llm = genai.GenerativeModel(Config.LLM_MODEL)
        
        logger.info("RAG Pipeline initialized with CBT support")
    
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
    
    def is_emotional_support_query(self, query):
        """Detect if query is about caregiver emotions vs technical care"""
        
        emotional_keywords = [
            'sad', 'lonely', 'miss', 'christmas', 'holiday', 'family',
            'feeling', 'overwhelmed', 'exhausted', "can't cope", 'depressed',
            'anxious', 'scared', 'worried', 'guilty', 'angry', 'frustrated',
            'alone', 'isolated', 'hopeless', 'breaking point', 'need support',
            'tired', 'burnt out', 'burnout', 'stressed', 'can\'t take it',
            'need a break', 'need help', 'struggling'
        ]
        
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in emotional_keywords)
    
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
            return None, []
        
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
                f"Research insight: {chunk_text[:500]}"  # Limit to 500 chars
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
    
    def generate_response(self, query, context=None, sources=None):
        """Generate response using Gemini with optional context"""
        
        # CRITICAL SAFETY CHECK: Detect diagnosis requests
        query_lower = query.lower()
        diagnosis_keywords = [
            'diagnose', 'diagnosis', 'what does he have', 'what does she have',
            'what condition', 'what disease', 'what is wrong', 'does he have',
            'does she have', 'is this alzheimer', 'is it dementia', 'could this be',
            'what type of dementia', 'which dementia', 'what stage',
            'is this normal aging', 'medical opinion', 'can you tell if',
            'symptom of what', 'caused by what'
        ]
        
        if any(keyword in query_lower for keyword in diagnosis_keywords):
            return {
                'answer': """⚠️ **I Cannot Provide Medical Diagnoses**

I'm a caregiving support assistant, not a medical professional. Only qualified healthcare providers (doctors, neurologists, geriatricians) can diagnose medical conditions.

**What I CAN Help With:**
• Practical caregiving strategies
• Daily care routines and activities
• Communication techniques
• Managing challenging behaviors
• Safety tips for the home
• Nutrition and meal planning
• Emotional support for caregivers

**What You Should Do:**
Please consult with:
• Primary care physician
• Neurologist or geriatrician
• Memory clinic or dementia specialist

They can conduct proper medical assessments, order appropriate tests, and provide accurate diagnosis and treatment plans.

**Would you like practical caregiving advice instead?**

---
⚠️ **Legal Disclaimer:** This AI system provides caregiving support only. It does not diagnose medical conditions, interpret symptoms, or provide medical advice. Always consult licensed healthcare professionals for medical decisions.""",
                'sources': []
            }
        
        # Build prompt based on whether we have research context
        if context:
            prompt = f"""{SYSTEM_PROMPT}

**Background research** (use subtly, don't quote directly):
{context}

**Caregiver says:** 
{query}

**Your response** (2-3 sentences, warm and practical):"""
        else:
            # No research - but still respond empathetically
            prompt = f"""{SYSTEM_PROMPT}

**Note:** No specific research papers match this query, but provide empathetic support based on general CBT principles for caregivers.

**Caregiver says:** 
{query}

**Your response** (warm, empathetic, 2-3 sentences):"""

        try:
            # Generate with Gemini
            response = self.llm.generate_content(
                prompt,
                generation_config={
                    'temperature': Config.TEMPERATURE,
                    'max_output_tokens': Config.MAX_OUTPUT_TOKENS
                }
            )
            
            answer = response.text.strip()
            
            return {
                'answer': answer,
                'sources': sources if sources else []
            }
        
        except Exception as e:
            logger.error(f"Generation error: {e}")
            return {
                'answer': "I hear you. That sounds really challenging. Can you tell me a bit more about what's going on?",
                'sources': []
            }
    
    def get_response(self, query):
        """Main RAG pipeline: Always respond empathetically"""
        try:
            # Check if this is emotional support query
            is_emotional = self.is_emotional_support_query(query)
            
            # Step 1: Search research papers
            search_results = self.search_research(query)
            
            # Step 2: Build context (even if empty)
            if search_results:
                context, sources = self.build_context(search_results)
            else:
                context, sources = None, []
                logger.info("No research found - will respond with general CBT support")
            
            # Step 3: ALWAYS generate response (with or without research)
            response = self.generate_response(query, context, sources)
            
            return response
        
        except Exception as e:
            logger.error(f"RAG pipeline error: {e}")
            return {
                'answer': "I hear you. That sounds really challenging. Can you tell me a bit more about what's going on?",
                'sources': []
            }


# ============================================
# SAFETY FUNCTIONS (called from app.py)
# ============================================

def check_safety_and_alert(user_message, code_hash, db_manager):
    """
    Check message safety and create admin alert if needed
    Returns: (is_safe, crisis_response_or_none)
    """
    message_lower = user_message.lower()
    
    # Crisis keywords
    crisis_patterns = {
        'suicide': ['kill myself', 'suicide', 'end my life', 'want to die', 'better off dead',
                   'no reason to live', 'take my own life', 'suicidal', 'end it all'],
        'self_harm': ['cut myself', 'hurt myself', 'self harm', 'self-harm', 'burn myself',
                     'harm myself', 'cutting', 'burning myself'],
        'harm_others': ['kill him', 'kill her', 'harm the patient', 'hurt him', 'hurt her',
                       'going to hurt', 'want to kill', 'strangle', 'suffocate', 'kill them'],
        'abuse': ['hitting him', 'hitting her', 'beating them', 'locked them in', 
                 'withholding food', 'leaving them alone for days', 'neglecting',
                 'hitting the patient', 'slapping']
    }
    
    # Check each category
    for alert_type, keywords in crisis_patterns.items():
        matched_keywords = [kw for kw in keywords if kw in message_lower]
        
        if matched_keywords:
            # LOG TO DATABASE
            try:
                with db_manager.get_connection() as conn:
                    cur = conn.cursor()
                    
                    # Redact message - only first 100 chars
                    excerpt = user_message[:100] + '...' if len(user_message) > 100 else user_message
                    
                    # Insert alert
                    cur.execute("""
                        INSERT INTO safety_alerts 
                        (code_hash, alert_type, severity, user_message_excerpt, detected_keywords)
                        VALUES (%s, %s, 'critical', %s, %s)
                    """, (code_hash, alert_type, excerpt, matched_keywords))
                    
                    conn.commit()
                    logger.critical(f"🚨 SAFETY ALERT: {alert_type} - Code: {code_hash[:8]}...")
                    
            except Exception as e:
                logger.error(f"Failed to log safety alert: {e}")
            
            # Return crisis response
            crisis_response = get_crisis_response(alert_type)
            return (False, crisis_response)
    
    # Safe - no crisis detected
    return (True, None)


def get_crisis_response(alert_type):
    """Return appropriate crisis response based on alert type"""
    
    responses = {
        'suicide': """**I'm very concerned about what you've shared.**

🚨 **Please get immediate help:**

**In the UK:**
- **999** - Emergency services (if in immediate danger)
- **Samaritans: 116 123** (24/7, free to call)
- **Crisis Text Line: Text SHOUT to 85258**
- **NHS 111** - Press option 2 for mental health crisis team

**You don't have to face this alone.** These services are confidential and staffed by trained professionals who can help you right now.

I'm not equipped to support you with suicidal thoughts - please reach out to these services immediately.""",

        'self_harm': """**I'm concerned about what you've shared.**

🚨 **Please get support:**

**In the UK:**
- **Samaritans: 116 123** (24/7, confidential)
- **Mind: 0300 123 3393** (Mon-Fri 9am-6pm)
- **NHS 111** - Press 2 for mental health support
- **Your GP** - can arrange urgent mental health assessment

This chat isn't designed to support self-harm. Please speak to a trained professional who can help you safely.""",

        'harm_others': """**I need to be direct with you.**

If you're having thoughts about harming someone, please:

- **Call 999** if you feel you might act on these thoughts
- **Contact your GP immediately** for urgent mental health support
- **Samaritans: 116 123** to talk through these feelings confidentially

If the person you care for is in immediate danger, call 999 now.

I can't continue this conversation - please speak to a professional who can help you with these thoughts.""",

        'abuse': """**What you're describing sounds very serious.**

If someone is being harmed or neglected:

**Report immediately:**
- **Call 999** if there's immediate danger
- **Adult Safeguarding: 0300 500 80 80** (report concerns)
- **Action on Elder Abuse Helpline: 080 8808 8141**
- **Your local social services department**

This is beyond what this chat can help with. Please contact these services - they're confidential and trained to investigate and protect vulnerable adults."""
    }
    
    return responses.get(alert_type, "Please contact emergency services if you're in crisis.")