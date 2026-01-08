"""
Technician Assistant Agent
Handles technician queries, extracts ticket context, and provides solutions based on similar tickets.
"""
from typing import Optional, Dict, List, Any
import json
import re
from src.database.db_connection import DatabaseConnection
from src.config import Config

class TechnicianAssistantAgent:
    """Agent for assisting technicians with tickets using semantic search and historical context"""
    
    def __init__(self, db_connection: DatabaseConnection):
        self.db_connection = db_connection

    def extract_request_info(self, input_text: str, model: str = 'llama-3.1-8b-instant') -> Optional[Dict]:
        """
        Extract ticket number and query from natural language input
        """
        # Quick check for ticket number pattern in text to avoid LLM call if obvious
        ticket_match = re.search(r'T\d{8}\.\d{6}', input_text)
        
        prompt = f"""
        Analyze the following technician's request and extract the ticket number and the specific technical query or problem they need help with.
        
        Input Text: "{input_text}"
        
        Instructions:
        1. Identify the ticket number (usually starts with 'T' followed by digits and dots, e.g., T20240108.123456).
        2. Identify the core technical question or assistance requested.
        3. If no ticket number is found, return null for ticket_number.
        
        Return ONLY a JSON object with keys: "ticket_number", "query".
        """
        
        print(f"🤖 Extracting request info from: {input_text}")
        extracted = self.db_connection.call_cortex_llm(prompt, model=model, json_response=True)
        
        # Fallback to regex if LLM missed it but it looks like a ticket number is there
        if extracted and not extracted.get("ticket_number") and ticket_match:
            extracted["ticket_number"] = ticket_match.group(0)
            
        return extracted

    def assist_technician(self, input_text: str, session_id: str = None, model: str = 'llama-3.3-70b-versatile') -> Dict[str, Any]:
        """
        Main method to handle technician assistance request with history support
        """
        print("\n" + "="*80)
        print("🛠️  TECHNICIAN ASSISTANCE - Starting (Conversational)")
        print("="*80)
        
        # Step 1: Extract ticket number and query
        info = self.extract_request_info(input_text)
        if not info:
            return {"success": False, "message": "Failed to parse your request."}
            
        ticket_number = info.get("ticket_number")
        technician_query = info.get("query")
        
        # If no ticket number and no session, we need a ticket number
        if not ticket_number and not session_id:
            return {
                "success": False, 
                "message": "I couldn't identify a ticket number in your request. Please provide the ticket number you are working on."
            }
            
        # If we have a session_id, we should find the ticket number if not provided
        if session_id and not ticket_number:
            # We don't have a direct session -> ticket mapping yet, but we could add one
            # For now, we assume provide ticket number or session_id is tied to one.
            pass

        # Step 2: Handle Session
        if not session_id and ticket_number:
            # Try to find existing session for this ticket or create new one
            session_id = self.db_connection.get_session_by_ticket(ticket_number)
            if not session_id:
                session_id = self.db_connection.create_chat_session(ticket_number)
                print(f"🆕 Created new session: {session_id}")
            else:
                print(f"🔄 Resuming existing session: {session_id}")
        
        print(f"🎫 Ticket Number: {ticket_number}")
        print(f"🆔 Session ID: {session_id}")
        print(f"❓ Query: {technician_query}")
        
        # Save user message
        self.db_connection.save_chat_message(session_id, 'user', input_text)
        
        # Step 3: Fetch current ticket details
        ticket_details = None
        if ticket_number:
            ticket_details = self.db_connection.get_ticket_by_number(ticket_number)
            
        if not ticket_details and not session_id:
            return {
                "success": False,
                "message": f"I couldn't find any information for ticket {ticket_number} in the database."
            }
            
        # Step 4: Load history
        history = self.db_connection.get_chat_history(session_id)
        
        # Step 5: Find similar tickets
        print("\nStep 5: Finding similar historical tickets...")
        similar_tickets = []
        if ticket_details:
            similar_tickets = self.db_connection.find_similar_tickets(
                title=ticket_details.get('title', ''),
                description=ticket_details.get('description', ''),
                limit=5
            )
        
        # Step 6: Generate assistant response with context
        print("\nStep 6: Generating assistant response...")
        response_prompt = self._build_conversational_prompt(
            ticket_details if ticket_details else {},
            technician_query,
            similar_tickets,
            history
        )
        
        llm_response = self.db_connection.call_cortex_llm(response_prompt, model=model, json_response=True)
        
        if not llm_response:
            return {
                "success": False,
                "message": "Failed to generate a response from the AI model."
            }
            
        def _ensure_string(val):
            if isinstance(val, list):
                return "\n".join(str(i) for i in val)
            return val

        analysis = _ensure_string(llm_response.get("analysis"))
        solution = _ensure_string(llm_response.get("solution"))
        
        # Save assistant message
        full_assistant_content = f"Analysis: {analysis}\n\nSolution: {solution}"
        self.db_connection.save_chat_message(session_id, 'assistant', full_assistant_content)
        
        return {
            "success": True,
            "session_id": session_id,
            "ticket_number": ticket_number,
            "analysis": analysis,
            "solution": solution,
            "sources": llm_response.get("sources", []),
            "follow_up_questions": llm_response.get("follow_up_questions", []),
            "original_query": technician_query
        }

    def _build_conversational_prompt(self, current_ticket: Dict, query: str, similar_tickets: List[Dict], history: List[Dict]) -> str:
        """Build a conversational prompt that considers history and reasoning"""
        
        history_text = ""
        for msg in history[:-1]: # Exclude the current user message which was just added
            role = "Technician" if msg['role'] == 'user' else "Assistant"
            history_text += f"{role}: {msg['content']}\n"

        prompt = f"""
        You are an advanced IT Support Reasoning Agent helping a technician solve a ticket.
        You take a 'Reasoning-First' approach, meaning you don't just retrieval data; you analyze the situation and address real-world constraints.
        
        **Current Ticket Information:**
        Ticket Number: {current_ticket.get('ticketnumber', 'Unknown')}
        Title: {current_ticket.get('title', 'Unknown')}
        Description: {current_ticket.get('description', 'Unknown')}
        
        **Conversation History:**
        {history_text}
        
        **Latest Technician Query:**
        "{query}"
        
        **Related Historical Data (for technical reference):**
        """
        
        for i, t in enumerate(similar_tickets, 1):
            prompt += f"\nSource {i} (Ticket {t.get('ticketnumber')}):"
            prompt += f"\nTitle: {t.get('title')}"
            prompt += f"\nResolution: {t.get('resolution')}"
            prompt += "\n"
            
        prompt += """
        **CRITICAL INSTRUCTIONS:**
        1. **ANALYZE BLOCKERS**: Look for real-world blockers in the technician's query (e.g., someone is unavailable, hardware is missing, permissions are denied).
        2. **PROVIDE PROCEDURAL SOLUTIONS**: If a blocker exists, do NOT just repeat technical steps. Suggest what to do about the blocker (e.g., contact a manager, check an alternative system, document the delay).
        3. **BE ANALYTICAL**: Explain WHY you are suggesting a specific path based on both the technical data and the current situation.
        4. **BE CONVERSATIONAL**: You are in a chat. Acknowledge previous context if relevant.
        5. **ASK FOLLOW-UPS**: If the query is vague or if knowing more would help you give a better answer, ask specific follow-up questions.
        
        **Output Format (JSON):**
        {
            "analysis": "A deep analysis of the situation, especially identifying any blockers or constraints mentioned...",
            "solution": "Clear, actionable steps addressing both the technical task and how to handle any mentioned blockers...",
            "sources": [
                {"ticket_number": "T...", "reason": "Why this historical ticket helped..."}
            ],
            "follow_up_questions": [
                "Question 1...",
                "Question 2..."
            ]
        }
        """
        return prompt
