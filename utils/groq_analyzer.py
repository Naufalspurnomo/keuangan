
"""
utils/groq_analyzer.py - AI-Powered Context & Intent Analyzer

WHY THIS APPROACH:
1. SIMPLE: One AI call replaces 450+ lines of rule-based code
2. SMART: Handles nyeleneh, typo, slang, mixed language automatically
3. EFFICIENT: Still within Groq Free tier for most use cases
4. FUTURE-PROOF: Adapts to new patterns without code changes

HYBRID STRATEGY:
- Layer 0 (Basic Filter): Rule-based (instant, free)
- Layer 1 (Smart Analysis): AI-powered (500ms, uses tokens but worth it)
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class GroqContextAnalyzer:
    """
    All-in-one analyzer using Groq AI.
    Replaces: ContextDetector + Normalizer + IntentClassifier
    """
    
    def __init__(self, groq_client):
        """
        Args:
            groq_client: Initialized Groq client
        """
        self.groq_client = groq_client
        
    def analyze_message(
        self, 
        message: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Single AI call to analyze everything.
        
        Args:
            message: {
                "text": str,
                "sender": str,
                "has_media": bool,
                "timestamp": datetime
            }
            context: {
                "is_reply_to_bot": bool,
                "replied_message_type": str or None,  # "TRANSACTION_REPORT" | "QUESTION" | etc
                "chat_type": str,  # "PRIVATE" | "GROUP"
                "recent_bot_interactions": list  # Last 3 interactions
            }
        
        Returns:
            {
                "should_respond": bool,
                "intent": str,
                "confidence": float,
                "reasoning": str,
                "extracted_data": dict  # If intent=REVISION, contains matched items etc
            }
        """
        
        # Build smart prompt
        prompt = self._build_analysis_prompt(message, context)
        
        try:
            # Single Groq API call
            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,  # Low for consistent classification
                max_tokens=400,  # Enough for analysis
                response_format={"type": "json_object"}  # Force JSON output
            )
            
            # Parse response
            result = json.loads(response.choices[0].message.content)
            
            logger.info(f"[GroqAnalyzer] Intent: {result.get('intent')} | "
                       f"Respond: {result.get('should_respond')} | "
                       f"Confidence: {result.get('confidence')}")
            
            return result
            
        except Exception as e:
            logger.error(f"[GroqAnalyzer] Error: {e}")
            
            # Check for Rate Limit specifically
            error_str = str(e).lower()
            if "rate limit" in error_str or "429" in error_str:
                import re
                # Extract wait time: "Please try again in 5m31.776s"
                wait_time = "beberapa saat"
                match = re.search(r"try again in ([0-9ms\.]+)", str(e))
                if match:
                    wait_time = match.group(1)
                
                return {
                    "should_respond": True,
                    "intent": "RATE_LIMIT",
                    "confidence": 1.0,
                    "reasoning": f"API Rate Limit. Wait: {wait_time}",
                    "extracted_data": {"wait_time": wait_time}
                }

            # Fallback to safe default
            return {
                "should_respond": False,
                "intent": "UNKNOWN",
                "confidence": 0.0,
                "reasoning": f"Error in analysis: {str(e)}",
                "extracted_data": {}
            }
    
    def _get_system_prompt(self) -> str:
        """
        Core system prompt that defines bot's intelligence.
        """
        return """You are a context-aware assistant for a financial bot in a WhatsApp/Telegram group.

YOUR JOB: Analyze messages to determine:
1. Should the bot respond? (vs stay silent for chitchat)
2. What is user's intent?
3. Extract relevant data if needed

CONTEXT AWARENESS RULES:
- If message REPLIES TO BOT: Very likely for bot (respond unless pure chitchat)
- If message MENTIONS BOT or starts with '/': Definitely for bot
- If message has FINANCIAL keywords (beli, bayar, saldo, etc): Likely for bot
- If message is CHITCHAT ("halo", "udah makan", etc) WITHOUT addressing bot: Stay silent
- If message is QUESTION ("berapa?", "gimana?") but NOT about finances: Stay silent UNLESS addressed to bot

INTENT TYPES:
1. RECORD_TRANSACTION - User wants to record new financial transaction
   Examples: "beli semen 500rb", "bayar tukang 2jt", "transfer 3.5jt ke supplier"
   
2. REVISION_REQUEST - User wants to revise existing transaction
   Examples: "revisi Dp 9.750.000", "salah harusnya 500rb", "ganti jadi 2jt"
   IMPORTANT: Only if replying to bot's transaction report!
   
3. QUERY_STATUS - User asking about financial data
   Examples: "berapa saldo?", "pengeluaran hari ini?", "laporan bulan ini"
   
4. ANSWER_PENDING - User answering bot's question
   Examples: "4" (when bot asked "pilih company 1-5"), "Renovasi Rumah" (when bot asked project name)
   IMPORTANT: Only if bot recently asked a question!
   
5. CONVERSATIONAL_QUERY - User asking bot for help/explanation (not financial data)
   Examples: "bot, cara export excel gimana?", "kenapa ga jalan?"
   
6. CHITCHAT - Casual conversation not for bot
   Examples: "selamat pagi", "udah makan belum?", "gimana kabar?"
   Should respond: NO (stay silent)

LANGUAGE HANDLING:
- Automatically handle typos: "berapee" → understand as "berapa"
- Handle slang: "anjir", "woi", "oi" → ignore, focus on core meaning
- Handle abbreviations: "tf" = transfer, "dp" = down payment
- Handle mixed language: English + Indonesian
- Handle informal: "males banget", "capek nih" → ignore filler words

FOR REVISION_REQUEST:
Extract:
- item_hint: What item to revise? (e.g., "Dp", "transfer", "biaya")
  Can be abbreviation or partial match!
- new_amount: What's the new amount?

OUTPUT FORMAT (JSON):
{
  "should_respond": true/false,
  "intent": "INTENT_TYPE",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation of decision",
  "extracted_data": {
    // For REVISION_REQUEST:
    "item_hint": "dp",
    "new_amount": 9750000
    
    // For RECORD_TRANSACTION:
    "amount": 500000,
    "description": "beli semen",
    "project_hint": "renovasi"
    
    // For QUERY_STATUS:
    "query_type": "expense" | "income" | "balance" | "report",
    "time_range": "today" | "this_week" | "this_month"
  }
}"""
    
    def _build_analysis_prompt(
        self, 
        message: Dict[str, Any],
        context: Dict[str, Any]
    ) -> str:
        """
        Build context-rich prompt for analysis.
        """
        
        # Context summary
        context_str = f"""CONTEXT:
- Chat Type: {context.get('chat_type', 'UNKNOWN')}
- Is Reply to Bot: {context.get('is_reply_to_bot', False)}"""
        
        if context.get('is_reply_to_bot'):
            context_str += f"\n- Replied Message Type: {context.get('replied_message_type', 'UNKNOWN')}"
        
        if context.get('recent_bot_interactions'):
            interactions = context['recent_bot_interactions'][:2]  # Last 2
            context_str += "\n- Recent Bot Interactions:"
            for i, interaction in enumerate(interactions, 1):
                context_str += f"\n  {i}. {interaction.get('type')} ({interaction.get('ago_seconds')}s ago)"
        
        # Message details
        message_str = f"""MESSAGE:
Text: "{message.get('text', '')}"
Sender: {message.get('sender', 'Unknown')}
Has Media: {message.get('has_media', False)}"""
        
        # Special case hints
        hints = []
        
        if context.get('is_reply_to_bot'):
            if context.get('replied_message_type') == 'TRANSACTION_REPORT':
                hints.append("User replied to transaction report - likely wants to REVISE")
            elif context.get('replied_message_type') == 'QUESTION':
                hints.append("User replied to bot's question - likely ANSWERING")
        
        if message.get('text', '').startswith('/'):
            hints.append("Message starts with '/' - explicit command for bot")
        
        hints_str = "\nHINTS:\n" + "\n".join(f"- {h}" for h in hints) if hints else ""
        
        # Combine
        full_prompt = f"""{context_str}

{message_str}
{hints_str}

TASK: Analyze this message and provide JSON response with your decision."""
        
        return full_prompt


# ============================================
# LAYER 0: Quick Pre-Filter (Rule-Based)
# ============================================

def should_quick_filter(message: Dict[str, Any]) -> Optional[str]:
    """
    Quick rule-based filter BEFORE calling AI.
    Only for OBVIOUS cases to save API calls.
    
    Returns:
        "IGNORE" - Definitely ignore (chitchat)
        "PROCESS" - Definitely process (explicit command)
        None - Uncertain, need AI analysis
    """
    text = (message.get('text') or '').lower().strip()
    
    # Quick accept: Explicit commands
    if text.startswith('/'):
        return "PROCESS"
    
    # Quick accept: Reply to bot
    if message.get('is_reply_to_bot'):
        return "PROCESS"
    
    # Quick accept: Has media + financial keyword
    if message.get('has_media'):
        financial_keywords = ['beli', 'bayar', 'transfer', 'catat', 'struk', 'bon']
        if any(kw in text for kw in financial_keywords):
            return "PROCESS"
    
    # Quick reject: Short non-financial chitchat
    if len(text) < 20:  # Increased from 10 to 20 to catch more short chitchat
        chitchat_exact = [
            'halo', 'hai', 'selamat pagi', 'selamat siang', 
            'selamat sore', 'selamat malam', 'apa kabar',
            'udah makan', 'makasih', 'thanks', 'ok', 'oke',
            'siap', 'mantap', 'baaal', 'test', 'tes'
        ]
        # Check explicit match or contained
        if any(c in text for c in chitchat_exact) and len(text.split()) <= 3:
             return "IGNORE"
             
        # Also simple exact match check
        if text in chitchat_exact: 
            return "IGNORE"
    
    # Uncertain - need AI
    return None


# ============================================
# USAGE EXAMPLE
# ============================================

async def smart_analyze_message(message, context, groq_client):
    """
    Main entry point for message analysis.
    
    Combines quick filter + AI analysis.
    """
    
    # STAGE 1: Quick Filter (Free, <1ms)
    quick_decision = should_quick_filter(message)
    
    if quick_decision == "IGNORE":
        logger.info("[QuickFilter] Obvious chitchat - ignored")
        return {
            "should_respond": False,
            "intent": "CHITCHAT",
            "confidence": 1.0,
            "reasoning": "Quick filter: obvious chitchat"
        }
    
    if quick_decision == "PROCESS":
        logger.info("[QuickFilter] Explicit command - will process")
        # Still need to determine intent, so continue to AI if complex
        # But if explicit command, we can just process it.
        # However, for hybrid approach, we might want AI to extract intent even for explicit commands.
        pass
    
    # STAGE 2: AI Analysis (500ms, uses tokens)
    analyzer = GroqContextAnalyzer(groq_client)
    result = analyzer.analyze_message(message, context)
    
    return result
