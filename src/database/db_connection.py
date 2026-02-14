"""
Database connection module for PostgreSQL
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime
from groq import Groq
import os
import json
import re
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from src.config import Config

class AttachmentInfo(BaseModel):
    attachment_id: Optional[int] = None
    filename: Optional[str] = None
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    file_path: Optional[str] = None
    processing_status: Optional[str] = None
    extracted_content: Optional[str] = None
    uploaded_at: Optional[Any] = None

# Initialize sentence transformer model for semantic search (lazy loading)
_semantic_model = None

def get_semantic_model():
    """Get or initialize the semantic search model"""
    global _semantic_model
    if _semantic_model is None:
        print("Loading semantic search model (first time only)...")
        _semantic_model = SentenceTransformer(Config.SEMANTIC_MODEL_NAME)
        print("✓ Semantic search model loaded")
    return _semantic_model


class DatabaseConnection:
    """Handles database connections and operations"""
    
    # Class-level flags for one-time initialization
    _tables_created = False
    _groq_initialized = False

    def __init__(self):
        self.db_config = Config.get_db_config()
        self.conn = None
        self.groq_client = None
        
        # Initialize components (lazy or one-time)
        if not DatabaseConnection._groq_initialized:
            self._init_groq()
            DatabaseConnection._groq_initialized = True
        
        if not DatabaseConnection._tables_created:
            self._ensure_tables_exist()
            DatabaseConnection._tables_created = True

    def _init_groq(self):
        """Initialize GROQ client"""
        groq_api_key = Config.GROQ_API_KEY
        
        if not groq_api_key:
            # Silent fallback or error only if needed
            return
        
        # Clean up the API key 
        groq_api_key = groq_api_key.strip()
        if groq_api_key.endswith('GROQ_API_KEY'):
            groq_api_key = groq_api_key[:-12].strip()
        
        try:
            self.groq_client = Groq(api_key=groq_api_key)
            # print("✓ GROQ client initialized successfully") # Silence this log
        except Exception as e:
            print(f"ERROR: Failed to initialize GROQ client: {e}")
            # raise # Don't crash app on llm fail
            pass
    
    def connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(**self.db_config)
            return self.conn
        except Exception as e:
            print(f"Error connecting to database: {e}")
            raise
    
    def get_connection(self):
        """Get database connection, create if not exists"""
        if self.conn is None or self.conn.closed:
            self.connect()
        return self.conn
    
    def execute_query(self, query: str, params: tuple = None, fetch: bool = True) -> Optional[List[Dict]]:
        """Execute a query and return results"""
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                
                # Commit for all operations (DML/DDL). 
                # For SELECT, commit just ends the transaction block.
                conn.commit()
                
                if fetch:
                    # Check if there are results to fetch (to avoid "no results to fetch" error)
                    if cur.description:
                        results = cur.fetchall()
                        return [dict(row) for row in results]
                return None
        except Exception as e:
            conn.rollback()
            print(f"Error executing query: {e}")
            raise
    
    def call_cortex_llm(self, prompt: str, model: str = 'llama3-8b-8192', json_response: bool = True) -> Any:
        """
        Call GROQ LLM API and parse response
        
        Args:
            prompt: The prompt to send to the LLM
            model: The model to use (default: llama3-8b-8192)
            json_response: Whether to enforce and parse JSON response (default: True)
        
        Returns:
            Parsed JSON as dict if json_response=True, else raw string
        """
        try:
            # Clean prompt
            prompt = prompt.strip()
            
            # Determine model name
            if '70b' in model.lower() or 'versatile' in model.lower():
                model_name = 'llama-3.3-70b-versatile'
            elif 'mixtral' in model.lower():
                model_name = 'llama-3.3-70b-versatile'
            elif 'llama3' in model.lower() or 'llama' in model.lower() or '8b' in model.lower():
                model_name = 'llama-3.1-8b-instant'
            else:
                model_name = 'llama-3.1-8b-instant'
            
            # Add JSON format instruction if requested
            if json_response:
                json_prompt = prompt + "\n\nIMPORTANT: Respond ONLY with valid JSON. Do not include any explanatory text before or after the JSON."
            else:
                json_prompt = prompt
            
            print(f"🤖 Calling GROQ API with model: {model_name}")
            print(f"📏 Prompt length: {len(json_prompt)} characters")
            print(f"⚙️  Temperature: 0.3, Max tokens: 2048")
            
            try:
                import time
                start_time = time.time()
                response = self.groq_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a helpful IT support assistant." + (" Respond with valid JSON only." if json_response else "")
                        },
                        {
                            "role": "user",
                            "content": json_prompt
                        }
                    ],
                    temperature=0.3,
                    max_tokens=2048
                )
                elapsed_time = time.time() - start_time
                print(f"⏱️  API call completed in {elapsed_time:.2f} seconds")
            except Exception as api_error:
                print(f"❌ GROQ API call failed: {api_error}")
                # Try with fallback model if the first one fails
                if model_name != 'llama-3.1-8b-instant':
                    print(f"🔄 Trying fallback model: llama-3.1-8b-instant")
                    try:
                        response = self.groq_client.chat.completions.create(
                            model='llama-3.1-8b-instant',
                            messages=[
                                {
                                    "role": "system",
                                    "content": "You are a helpful IT support assistant." + (" Respond with valid JSON only." if json_response else "")
                                },
                                {
                                    "role": "user",
                                    "content": json_prompt
                                }
                            ],
                            temperature=0.3,
                            max_tokens=2048
                        )
                    except Exception as fallback_error:
                        print(f"Fallback model also failed: {fallback_error}")
                        raise api_error  # Raise original error
                else:
                    raise
            
            content = response.choices[0].message.content.strip()
            print(f"📥 Raw response received ({len(content)} characters)")
            
            if not json_response:
                return content
            
            # Remove markdown code blocks if present
            original_content = content
            if content.startswith('```json'):
                content = content[7:]
                print("🧹 Removed ```json markdown wrapper")
            elif content.startswith('```'):
                content = content[3:]
                print("🧹 Removed ``` markdown wrapper")
            if content.endswith('```'):
                content = content[:-3]
                print("🧹 Removed closing ``` markdown wrapper")
            content = content.strip()
            
            # Try to parse JSON
            try:
                result = json.loads(content)
                print("✅ JSON parsed successfully")
                print(f"📊 Parsed keys: {list(result.keys())}")
                return result
            except json.JSONDecodeError as e:
                print(f"❌ JSON decode error: {e}")
                print(f"📄 Response content (first 500 chars): {content[:500]}")
                print("🔍 Attempting to extract JSON from response...")
                # Try to extract JSON from text
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    try:
                        result = json.loads(json_match.group())
                        print("✅ Successfully extracted and parsed JSON")
                        return result
                    except json.JSONDecodeError as e2:
                        print(f"❌ Failed to parse extracted JSON: {e2}")
                        print(f"📄 Extracted JSON (first 500 chars): {json_match.group()[:500]}")
                        return None
                else:
                    print(f"❌ Failed to find JSON in response")
                    print(f"📄 Full response: {content}")
                    return None
                    
        except Exception as e:
            print(f"❌ Error calling GROQ LLM: {e}")
            import traceback
            print("📋 Full traceback:")
            traceback.print_exc()
            return None
    
    def find_similar_tickets(self, title: str, description: str, limit: int = 20) -> List[Dict]:
        """
        Find similar tickets from historical data using semantic search (embeddings)
        
        Args:
            title: Ticket title
            description: Ticket description
            limit: Maximum number of similar tickets to return
        
        Returns:
            List of similar ticket dictionaries
        """
        print(f"\n🔍 Finding similar tickets using semantic search...")
        print(f"   Search text: {title[:100]}{'...' if len(title) > 100 else ''}")
        print(f"   Limit: {limit}")
        
        conn = self.get_connection()
        try:
            # Get semantic model
            model = get_semantic_model()
            
            # Create embedding for the search query
            search_text = f"{title} {description}".strip()
            if not search_text:
                search_text = title
            
            print(f"   🧠 Generating embedding for search query...")
            query_embedding = model.encode([search_text])[0]
            
            # Fetch a batch of tickets from database for comparison
            batch_size = Config.SEMANTIC_SEARCH_BATCH_SIZE
            
            query = f"""
                (SELECT 
                    ticketnumber, title, description, issuetype, subissuetype,
                    ticketcategory, tickettype, priority, status, createdate,
                    resolveddatetime, resolution, 'closed' as source_table
                FROM closed_tickets
                WHERE title IS NOT NULL OR description IS NOT NULL)
                UNION ALL
                (SELECT 
                    ticketnumber, title, description, issuetype, subissuetype,
                    ticketcategory, tickettype, priority, status, createdate,
                    resolveddatetime, resolution, 'resolved' as source_table
                FROM resolved_tickets
                WHERE title IS NOT NULL OR description IS NOT NULL)
                UNION ALL
                (SELECT 
                    ticketnumber, title, description, issuetype, subissuetype,
                    ticketcategory, tickettype, priority, status, createdate,
                    resolveddatetime, resolution, 'new' as source_table
                FROM new_tickets
                WHERE title IS NOT NULL OR description IS NOT NULL)
                ORDER BY createdate DESC
                LIMIT %s
            """
            
            print(f"   📊 Fetching up to {batch_size} tickets from all tables for comparison...")
            candidate_tickets = self.execute_query(query, (batch_size,))
            
            if not candidate_tickets:
                print(f"   ⚠️  No tickets found in database")
                return []
            
            # Prepare text for embedding (combine title and description)
            ticket_texts = []
            for ticket in candidate_tickets:
                ticket_title = ticket.get('title', '') or ''
                ticket_desc = ticket.get('description', '') or ''
                combined_text = f"{ticket_title} {ticket_desc}".strip()
                ticket_texts.append(combined_text)
            
            print(f"   🧠 Generating embeddings for {len(ticket_texts)} tickets...")
            # Generate embeddings for all candidate tickets
            ticket_embeddings = model.encode(ticket_texts, show_progress_bar=False)
            
            # Calculate cosine similarity
            print(f"   📐 Calculating semantic similarity...")
            similarities = cosine_similarity([query_embedding], ticket_embeddings)[0]
            
            # Get top similar tickets
            top_indices = np.argsort(similarities)[::-1][:limit]
            
            # Build results with similarity scores
            results = []
            for idx in top_indices:
                ticket = candidate_tickets[idx].copy()
                ticket['similarity_score'] = float(similarities[idx])
                results.append(ticket)
            
            # Filter out very low similarity scores
            filtered_results = [t for t in results if t['similarity_score'] >= Config.SIMILARITY_THRESHOLD]
            
            if filtered_results:
                print(f"   ✅ Found {len(filtered_results)} semantically similar tickets")
                print(f"   📋 Top similar tickets (with similarity scores):")
                for i, ticket in enumerate(filtered_results[:5], 1):
                    ticket_title = ticket.get('title', 'N/A')[:60]
                    similarity = ticket['similarity_score']
                    print(f"      {i}. [{similarity:.3f}] {ticket_title}...")
                
                # Remove similarity_score before returning (it's just for logging)
                for ticket in filtered_results:
                    ticket.pop('similarity_score', None)
                
                return filtered_results[:limit]
            else:
                print(f"   ⚠️  No tickets found with similarity >= {Config.SIMILARITY_THRESHOLD}, using most recent")
                return results[:limit]
            
        except Exception as e:
            print(f"   ❌ Error finding similar tickets: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to simple query on error
            try:
                fallback_query = """
                    SELECT ticketnumber, title, description, resolution, 'closed' as source_table
                    FROM closed_tickets ORDER BY createdate DESC LIMIT %s
                """
                return self.execute_query(fallback_query, (limit,)) or []
            except:
                return []
    
    def insert_ticket(self, ticket_data: Dict[str, Any]) -> Optional[str]:
        """
        Insert a new ticket into the new_tickets table
        
        Args:
            ticket_data: Dictionary containing ticket fields
        
        Returns:
            Ticket number if successful, None otherwise
        """
        conn = self.get_connection()
        try:
            # Generate ticket number if not provided
            if 'ticketnumber' not in ticket_data or not ticket_data['ticketnumber']:
                from datetime import datetime
                ticket_number = f"T{datetime.now().strftime('%Y%m%d')}.{datetime.now().strftime('%H%M%S')}"
                ticket_data['ticketnumber'] = ticket_number
            
            # Prepare columns and values
            columns = [k for k in ticket_data.keys() if ticket_data[k] is not None]
            values = [ticket_data[k] for k in columns]
            placeholders = ', '.join(['%s'] * len(columns))
            
            query = f"""
                INSERT INTO new_tickets ({', '.join(columns)})
                VALUES ({placeholders})
                RETURNING ticketnumber
            """
            
            with conn.cursor() as cur:
                cur.execute(query, values)
                ticket_number = cur.fetchone()[0]
                conn.commit()
                return ticket_number
                
        except Exception as e:
            conn.rollback()
            print(f"Error inserting ticket: {e}")
            raise
    
    def get_all_tickets(
        self, 
        limit: int = 50, 
        offset: int = 0,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        issuetype: Optional[str] = None,
        user_id: Optional[str] = None,
        companyid: Optional[str] = None,
        assigned_tech_id: Optional[str] = None,
        order_by: str = 'createdate',
        order_direction: str = 'DESC'
    ) -> Dict[str, Any]:
        """
        Get all tickets with pagination, filtering, and sorting
        
        Args:
            limit: Maximum number of tickets to return (default: 50, max: 1000)
            offset: Number of tickets to skip (default: 0)
            status: Filter by status (optional)
            priority: Filter by priority (optional)
            issuetype: Filter by issue type (optional)
            user_id: Filter by user ID (optional)
            companyid: Filter by company ID (optional)
            assigned_tech_id: Filter by assigned technician ID (optional)
            order_by: Column to order by (default: 'createdate')
            order_direction: Order direction 'ASC' or 'DESC' (default: 'DESC')
        
        Returns:
            Dictionary with 'tickets' list and 'total' count
        """
        conn = self.get_connection()
        try:
            # Validate and sanitize inputs
            limit = min(max(1, limit), 1000)  # Between 1 and 1000
            offset = max(0, offset)
            order_direction = order_direction.upper() if order_direction.upper() in ['ASC', 'DESC'] else 'DESC'
            
            # Allowed columns for ordering (prevent SQL injection)
            allowed_order_columns = [
                'createdate', 'duedatetime', 'ticketnumber', 'title', 
                'status', 'priority', 'issuetype', 'lastactivitydate'
            ]
            if order_by.lower() not in [col.lower() for col in allowed_order_columns]:
                order_by = 'createdate'
            
            # Build WHERE clause
            where_conditions = []
            params = []
            
            if status:
                where_conditions.append("nt.status = %s")
                params.append(status)
            
            if priority:
                where_conditions.append("nt.priority = %s")
                params.append(priority)
            
            if issuetype:
                where_conditions.append("nt.issuetype = %s")
                params.append(issuetype)
            
            if user_id:
                where_conditions.append("nt.user_id = %s")
                params.append(user_id)
            
            if companyid:
                where_conditions.append("nt.companyid = %s")
                params.append(companyid)
                
            if assigned_tech_id:
                where_conditions.append("latest_assign.tech_id = %s")
                params.append(assigned_tech_id)
            
            where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
            
            # Get total count (needs lateral join if filtering by tech)
            if assigned_tech_id:
                count_query = f"""
                    SELECT COUNT(*) 
                    FROM new_tickets nt
                    LEFT JOIN LATERAL (
                        SELECT tech_id 
                        FROM ticket_assignments 
                        WHERE ticket_number = nt.ticketnumber 
                        ORDER BY assigned_at DESC 
                        LIMIT 1
                    ) latest_assign ON true
                    WHERE {where_clause}
                """
            else:
                count_query = f"SELECT COUNT(*) FROM new_tickets nt WHERE {where_clause}"
                
            with conn.cursor() as cur:
                cur.execute(count_query, tuple(params))
                total = cur.fetchone()[0]
            
            # Get tickets with pagination and assigned technician info
            query = f"""
                SELECT 
                    nt.ticketnumber, nt.title, nt.description, nt.user_id, nt.createdate, 
                    nt.duedatetime, nt.status, nt.priority, nt.issuetype, nt.subissuetype,
                    nt.ticketcategory, nt.tickettype, nt.lastactivitydate, nt.resolveddatetime,
                    nt.resolution, nt.companyid, nt.queueid, nt.estimatedhours,
                    latest_assign.tech_id as assigned_tech_id,
                    td.tech_name as assigned_tech_name
                FROM new_tickets nt
                LEFT JOIN LATERAL (
                    SELECT tech_id 
                    FROM ticket_assignments 
                    WHERE ticket_number = nt.ticketnumber 
                    ORDER BY assigned_at DESC 
                    LIMIT 1
                ) latest_assign ON true
                LEFT JOIN technician_data td ON latest_assign.tech_id = td.tech_id
                WHERE {where_clause}
                ORDER BY nt.{order_by} {order_direction}
                LIMIT %s OFFSET %s
            """
            
            params.extend([limit, offset])
            results = self.execute_query(query, tuple(params))
            
            return {
                'tickets': results or [],
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + limit) < total
            }
            
        except Exception as e:
            print(f"Error getting tickets: {e}")
            raise
    
    def get_ticket_by_number(self, ticket_number: str) -> Optional[Dict]:
        """
        Get ticket details by ticket number searching across all tables
        
        Args:
            ticket_number: The ticket number to retrieve
        
        Returns:
            Dictionary with ticket details or None if not found
        """
        query = """
            SELECT ticketnumber, title, description, status, issuetype, resolution, 'new' as source_table FROM new_tickets WHERE ticketnumber = %s
            UNION ALL
            SELECT ticketnumber, title, description, status, issuetype, resolution, 'resolved' as source_table FROM resolved_tickets WHERE ticketnumber = %s
            UNION ALL
            SELECT ticketnumber, title, description, status, issuetype, resolution, 'closed' as source_table FROM closed_tickets WHERE ticketnumber = %s
        """
        params = (ticket_number, ticket_number, ticket_number)
        results = self.execute_query(query, params)
        return results[0] if results else None

    def _ensure_tables_exist(self):
        """Ensure all required tables exist, create them if they don't"""
        conn = self.get_connection()
        try:
            # Check if new_tickets table exists
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'new_tickets'
                    );
                """)
                table_exists = cur.fetchone()[0]
                
                if not table_exists:
                    print("Tables not found. Creating tables...")
                    self._create_tables(conn)
                    self._create_closed_tickets_table(conn)
                else:
                    # Check for tickets_context table
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = 'public' 
                            AND table_name = 'tickets_context'
                        );
                    """)
                    if not cur.fetchone()[0]:
                         print("tickets_context table not found. Creating it...")
                         self._create_tables(conn) # Re-run create tables which now includes it
                    
                    # Check for ticket_assignments table
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = 'public' 
                            AND table_name = 'ticket_assignments'
                        );
                    """)
                    if not cur.fetchone()[0]:
                         print("ticket_assignments table not found. Creating it...")
                         self._create_tables(conn)
                         
                    # Check if closed_tickets table exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = 'public' 
                            AND table_name = 'closed_tickets'
                        );
                    """)
                    closed_table_exists = cur.fetchone()[0]
                    
                    if not closed_table_exists:
                        print("closed_tickets table not found. Creating it...")
                        self._create_closed_tickets_table(conn)
                    else:
                        # Check if chat_sessions table exists
                        cur.execute("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables 
                                where table_schema = 'public' 
                                AND table_name = 'chat_sessions'
                            );
                        """)
                        chat_table_exists = cur.fetchone()[0]
                        
                        if not chat_table_exists:
                            print("chat history tables not found. Creating them...")
                            self._create_tables(conn)
                        else:
                            pass # This else block is now empty as the print moves out
                    
                    print("✓ Database tables exist")
                
                # Check for audit_logs table
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'audit_logs'
                    );
                """)
                if not cur.fetchone()[0]:
                     print("audit_logs table not found. Creating it...")
                     self._create_tables(conn)

                # Check for system_settings table
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'system_settings'
                    );
                """)
                if not cur.fetchone()[0]:
                     print("system_settings table not found. Creating it...")
                     self._create_tables(conn)

                # Check for notifications table
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'notifications'
                    );
                """)
                if not cur.fetchone()[0]:
                     print("notifications table not found. Creating it...")
                     self._create_notifications_table(conn)

                # Check and add missing columns (migrations)
                self._ensure_columns_exist(conn)
        except Exception as e:
            print(f"Error checking tables: {e}")
            # Try to create tables anyway
            try:
                self._create_tables(conn)
            except Exception as create_error:
                print(f"Error creating tables: {create_error}")
    
    def _ensure_columns_exist(self, conn):
        """Ensure all required columns exist in tables (migrations)"""
        try:
            with conn.cursor() as cur:
                # 1. new_tickets: user_id
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_schema = 'public' 
                        AND table_name = 'new_tickets' 
                        AND column_name = 'user_id'
                    );
                """)
                if not cur.fetchone()[0]:
                    print("user_id column not found in new_tickets table. Adding it...")
                    cur.execute("ALTER TABLE new_tickets ADD COLUMN user_id VARCHAR(100);")
                
                # 2. user_data: companyid, role, password_hash, status
                columns_to_check = {
                    'companyid': 'VARCHAR(100)',
                    'role': "VARCHAR(50) DEFAULT 'user'",
                    'password_hash': 'VARCHAR(255)',
                    'status': "VARCHAR(20) DEFAULT 'active'"
                }
                for col, dtype in columns_to_check.items():
                    cur.execute(f"""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns 
                            WHERE table_schema = 'public' 
                            AND table_name = 'user_data' 
                            AND column_name = '{col}'
                        );
                    """)
                    if not cur.fetchone()[0]:
                        print(f"{col} column not found in user_data table. Adding it...")
                        cur.execute(f"ALTER TABLE user_data ADD COLUMN {col} {dtype};")

                # 3. technician_data: companyid, role, status
                tech_columns = {
                    'companyid': 'VARCHAR(100)',
                    'role': "VARCHAR(50) DEFAULT 'technician'",
                    'status': "VARCHAR(20) DEFAULT 'active'",
                    'password_hash': 'VARCHAR(255)'
                }
                for col, dtype in tech_columns.items():
                    cur.execute(f"""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns 
                            WHERE table_schema = 'public' 
                            AND table_name = 'technician_data' 
                            AND column_name = '{col}'
                        );
                    """)
                    if not cur.fetchone()[0]:
                         print(f"{col} column not found in technician_data table. Adding it...")
                         cur.execute(f"ALTER TABLE technician_data ADD COLUMN {col} {dtype};")

                # 4. organizations: status, subscription_plan
                org_columns = {
                    'status': "VARCHAR(20) DEFAULT 'active'",
                    'subscription_plan': "VARCHAR(50) DEFAULT 'free'"
                }
                # First check if organizations table exists (it might not be in create_tables.sql yet)
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'organizations'
                    );
                """)
                if cur.fetchone()[0]:
                    for col, dtype in org_columns.items():
                        cur.execute(f"""
                            SELECT EXISTS (
                                SELECT FROM information_schema.columns 
                                WHERE table_schema = 'public' 
                                AND table_name = 'organizations' 
                                AND column_name = '{col}'
                            );
                        """)
                        if not cur.fetchone()[0]:
                            print(f"{col} column not found in organizations table. Adding it...")
                            cur.execute(f"ALTER TABLE organizations ADD COLUMN {col} {dtype};")

                # 5. ticket_assignments: assignment_reason
                # Check if ticket_assignments table exists first
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'ticket_assignments'
                    );
                """)
                if cur.fetchone()[0]:
                     cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns 
                            WHERE table_schema = 'public' 
                            AND table_name = 'ticket_assignments' 
                            AND column_name = 'assignment_reason'
                        );
                    """)
                     if not cur.fetchone()[0]:
                        print("assignment_reason column not found in ticket_assignments table. Adding it...")
                        cur.execute("ALTER TABLE ticket_assignments ADD COLUMN assignment_reason TEXT;")
                     
                     # Check for skill_match_score
                     cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns 
                            WHERE table_schema = 'public' 
                            AND table_name = 'ticket_assignments' 
                            AND column_name = 'skill_match_score'
                        );
                    """)
                     if not cur.fetchone()[0]:
                        print("skill_match_score column not found in ticket_assignments table. Adding it...")
                        cur.execute("ALTER TABLE ticket_assignments ADD COLUMN skill_match_score FLOAT;")

                conn.commit()
                print("✓ Schema migration check complete")
        except Exception as e:
            print(f"Error ensuring columns exist: {e}")
            conn.rollback()
    
    def _create_tables(self, conn):
        """Create all required database tables"""
        # We ignore the external SQL file to ensure our internal definition is the source of truth
        # sql_file = os.path.join(...) 
        
        # Use inline definition
        sql_script = """
-- Table 1: new_tickets
CREATE TABLE IF NOT EXISTS new_tickets (
    id SERIAL PRIMARY KEY,
    companyid VARCHAR(100),
    completeddate TIMESTAMP,
    createdate TIMESTAMP,
    description TEXT,
    duedatetime TIMESTAMP,
    estimatedhours NUMERIC(10, 2),
    firstresponsedatetime TIMESTAMP,
    issuetype VARCHAR(100),
    lastactivitydate TIMESTAMP,
    priority VARCHAR(50),
    queueid VARCHAR(100),
    resolution TEXT,
    resolutionplandatetime TIMESTAMP,
    resolveddatetime TIMESTAMP,
    status VARCHAR(50),
    subissuetype VARCHAR(100),
    ticketcategory VARCHAR(100),
    ticketnumber VARCHAR(100) UNIQUE,
    tickettype VARCHAR(100),
    title TEXT,
    user_id VARCHAR(100)
);

-- Table 2: resolved_tickets
CREATE TABLE IF NOT EXISTS resolved_tickets (
    id SERIAL PRIMARY KEY,
    companyid VARCHAR(100),
    completeddate TIMESTAMP,
    createdate TIMESTAMP,
    description TEXT,
    duedatetime TIMESTAMP,
    estimatedhours NUMERIC(10, 2),
    firstresponsedatetime TIMESTAMP,
    issuetype VARCHAR(100),
    lastactivitydate TIMESTAMP,
    priority VARCHAR(50),
    queueid VARCHAR(100),
    resolution TEXT,
    resolutionplandatetime TIMESTAMP,
    resolveddatetime TIMESTAMP,
    status VARCHAR(50),
    subissuetype VARCHAR(100),
    ticketcategory VARCHAR(100),
    ticketnumber VARCHAR(100) UNIQUE,
    tickettype VARCHAR(100),
    title TEXT
);

-- Table 3: technician_data
CREATE TABLE IF NOT EXISTS technician_data (
    tech_id VARCHAR(100) PRIMARY KEY,
    tech_name VARCHAR(255) NOT NULL,
    tech_mail VARCHAR(255) UNIQUE NOT NULL,
    tech_password VARCHAR(255),
    skills TEXT,
    no_tickets_assigned INTEGER DEFAULT 0,
    solved_tickets INTEGER DEFAULT 0,
    current_workload INTEGER DEFAULT 0,
    available BOOLEAN DEFAULT TRUE
);

-- Table 4: user_data
CREATE TABLE IF NOT EXISTS user_data (
    user_id VARCHAR(100) PRIMARY KEY,
    user_name VARCHAR(255) NOT NULL,
    user_mail VARCHAR(255) UNIQUE NOT NULL,
    user_password VARCHAR(255),
    no_tickets_raised INTEGER DEFAULT 0,
    current_raised_ticket VARCHAR(100),
    available BOOLEAN DEFAULT TRUE
);

-- Table 5: closed_tickets (for historical ticket data and similarity search)
CREATE TABLE IF NOT EXISTS closed_tickets (
    id SERIAL PRIMARY KEY,
    companyid VARCHAR(100),
    completeddate TIMESTAMP,
    createdate TIMESTAMP,
    description TEXT,
    duedatetime TIMESTAMP,
    estimatedhours NUMERIC(10, 2),
    firstresponsedatetime TIMESTAMP,
    issuetype VARCHAR(100),
    lastactivitydate TIMESTAMP,
    priority VARCHAR(50),
    queueid VARCHAR(100),
    resolution TEXT,
    resolutionplandatetime TIMESTAMP,
    resolveddatetime TIMESTAMP,
    status VARCHAR(50),
    subissuetype VARCHAR(100),
    ticketcategory VARCHAR(100),
    ticketnumber VARCHAR(100) UNIQUE,
    tickettype VARCHAR(100),
    title TEXT
);

-- Table 6: ticket_assignments
CREATE TABLE IF NOT EXISTS ticket_assignments (
    assignment_id SERIAL PRIMARY KEY,
    ticket_number VARCHAR(100) NOT NULL,
    tech_id VARCHAR(100) NOT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assignment_reason TEXT,
    skills_matched TEXT,
    skill_match_score FLOAT, 
    status VARCHAR(20) DEFAULT 'active'
);

-- Table 7: tickets_context
CREATE TABLE IF NOT EXISTS tickets_context (
    id SERIAL PRIMARY KEY,
    ticket_number VARCHAR(100) NOT NULL,
    title TEXT,
    description TEXT,
    extracted_text TEXT,
    image_analysis JSONB,
    table_data_parsed JSONB,
    entities JSONB,
    context_summary TEXT,
    file_metadata JSONB,
    resolved_at TIMESTAMP,
    resolution_category VARCHAR(100),
    assigned_technician_id VARCHAR(100),
    human_feedback JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table 8: audit_logs
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id SERIAL PRIMARY KEY,
    user_id VARCHAR(100),
    action VARCHAR(255) NOT NULL,
    resource_type VARCHAR(100),
    resource_id VARCHAR(100),
    details JSONB,
    ip_address VARCHAR(50),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table 9: system_settings
CREATE TABLE IF NOT EXISTS system_settings (
    setting_key VARCHAR(100) PRIMARY KEY,
    setting_value JSONB,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100)
);

-- Table 10: organizations (Ensuring existence if not already created by other scripts)
CREATE TABLE IF NOT EXISTS organizations (
    id SERIAL PRIMARY KEY,
    companyid VARCHAR(50) UNIQUE NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    admin_email VARCHAR(255),
    plan VARCHAR(50) DEFAULT 'Free',
    status VARCHAR(50) DEFAULT 'Active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
        """
        
        with conn.cursor() as cur:
            cur.execute(sql_script)
            conn.commit()
            print("✓ Database tables created successfully!")
    
    def _create_closed_tickets_table(self, conn):
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS closed_tickets (
                    id SERIAL PRIMARY KEY,
                    companyid VARCHAR(100),
                    completeddate TIMESTAMP,
                    createdate TIMESTAMP,
                    description TEXT,
                    duedatetime TIMESTAMP,
                    estimatedhours NUMERIC(10, 2),
                    firstresponsedatetime TIMESTAMP,
                    issuetype VARCHAR(100),
                    lastactivitydate TIMESTAMP,
                    priority VARCHAR(50),
                    queueid VARCHAR(100),
                    resolution TEXT,
                    resolutionplandatetime TIMESTAMP,
                    resolveddatetime TIMESTAMP,
                    status VARCHAR(50),
                    subissuetype VARCHAR(100),
                    ticketcategory VARCHAR(100),
                    ticketnumber VARCHAR(100) UNIQUE,
                    tickettype VARCHAR(100),
                    title TEXT,
                    user_id VARCHAR(100)
                );
            """)
            conn.commit()

    def _create_notifications_table(self, conn):
        """Create notifications table"""
        try:
            with conn.cursor() as cur:
                # Use the SQL file we just created
                sql_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'create_notifications.sql')
                if os.path.exists(sql_file_path):
                    with open(sql_file_path, 'r') as f:
                        sql_script = f.read()
                        cur.execute(sql_script)
                else:
                    # Fallback inline creation
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS notifications (
                            notification_id SERIAL PRIMARY KEY,
                            user_id VARCHAR(255) NOT NULL,
                            title VARCHAR(255) NOT NULL,
                            message TEXT NOT NULL,
                            type VARCHAR(50) DEFAULT 'info',
                            read BOOLEAN DEFAULT FALSE,
                            link VARCHAR(255),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            -- Foreign key handled loosely or implicitly if users not yet synced
                        );
                        CREATE INDEX IF NOT EXISTS idx_notifications_user_unread ON notifications(user_id) WHERE read = FALSE;
                    """)
                conn.commit()
                print("✓ Notifications table created")
        except Exception as e:
            conn.rollback()
            print(f"Error creating notifications table: {e}")
    
    def close(self):
        """Close database connection"""
        if self.conn and not self.conn.closed:
            self.conn.close()

    def create_chat_session(self, ticket_number: str) -> Optional[str]:
        """Create a new chat session for a ticket"""
        query = "INSERT INTO chat_sessions (ticket_number) VALUES (%s) RETURNING session_id"
        result = self.execute_query(query, (ticket_number,))
        return str(result[0]['session_id']) if result else None

    def save_chat_message(self, session_id: str, role: str, content: str):
        """Save a chat message to history"""
        query = "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, %s, %s)"
        self.execute_query(query, (session_id, role, content), fetch=False)

    def get_chat_history(self, session_id: str, limit: int = 10) -> List[Dict]:
        """Retrieve chat history for a session"""
        query = """
            SELECT role, content, timestamp 
            FROM chat_messages 
            WHERE session_id = %s 
            ORDER BY timestamp ASC 
            LIMIT %s
        """
        results = self.execute_query(query, (session_id, limit))
        return results if results else []

    def get_session_by_ticket(self, ticket_number: str) -> Optional[str]:
        """Get the latest session ID for a ticket"""
        query = "SELECT session_id FROM chat_sessions WHERE ticket_number = %s ORDER BY created_at DESC LIMIT 1"
        result = self.execute_query(query, (ticket_number,))
        if result:
            return str(result[0]['session_id'])
        return None

    # ========== Organization Management Methods ==========
    
    def get_next_companyid(self) -> str:
        """
        Generate next companyid in format 0001, 0002, etc.
        
        Returns:
            Next available companyid with zero-padding
        """
        query = """
            SELECT companyid FROM organizations 
            ORDER BY CAST(companyid AS INTEGER) DESC 
            LIMIT 1
        """
        result = self.execute_query(query)
        
        if result and result[0].get('companyid'):
            last_id = int(result[0]['companyid'])
            next_id = last_id + 1
        else:
            next_id = 1
        
        # Zero-pad to 4 digits
        return str(next_id).zfill(4)
    
    def create_organization(self, organization_data: Dict[str, Any]) -> Optional[str]:
        """
        Create a new organization with auto-generated companyid
        
        Args:
            organization_data: Dictionary with company_name, company_email, contact_phone, address
        
        Returns:
            companyid if successful, None otherwise
        """
        conn = self.get_connection()
        try:
            # Generate next companyid
            companyid = self.get_next_companyid()
            
            # Prepare insert query
            query = """
                INSERT INTO organizations (companyid, company_name, company_email, contact_phone, address)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING companyid
            """
            
            params = (
                companyid,
                organization_data.get('company_name'),
                organization_data.get('company_email'),
                organization_data.get('contact_phone'),
                organization_data.get('address')
            )
            
            with conn.cursor() as cur:
                cur.execute(query, params)
                result_companyid = cur.fetchone()[0]
                conn.commit()
                return result_companyid
                
        except Exception as e:
            conn.rollback()
            print(f"Error creating organization: {e}")
            raise
    
    def get_organization_by_companyid(self, companyid: str) -> Optional[Dict]:
        """
        Get organization details by companyid
        
        Args:
            companyid: The company ID to retrieve
        
        Returns:
            Dictionary with organization details or None if not found
        """
        query = "SELECT * FROM organizations WHERE companyid = %s"
        results = self.execute_query(query, (companyid,))
        return results[0] if results else None
    
    def get_all_organizations(self, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """
        Get all organizations with pagination
        
        Args:
            limit: Maximum number of organizations to return
            offset: Number of organizations to skip
        
        Returns:
            Dictionary with organizations list and total count
        """
        conn = self.get_connection()
        try:
            # Get total count
            count_query = "SELECT COUNT(*) FROM organizations"
            with conn.cursor() as cur:
                cur.execute(count_query)
                total = cur.fetchone()[0]
            
            # Get organizations with pagination
            query = """
                SELECT * FROM organizations
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """
            results = self.execute_query(query, (limit, offset))
            
            return {
                'organizations': results or [],
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + limit) < total
            }
        except Exception as e:
            print(f"Error getting organizations: {e}")
            raise

    def update_organization(self, companyid: str, update_data: Dict[str, Any]) -> bool:
        """
        Update organization details
        """
        conn = self.get_connection()
        try:
            allowed_fields = ['company_name', 'company_email', 'contact_phone', 'address', 'status', 'subscription_plan']
            
            fields = []
            values = []
            
            for key, value in update_data.items():
                if key in allowed_fields:
                    fields.append(f"{key} = %s")
                    values.append(value)
            
            if not fields:
                return False
                
            values.append(companyid)
            query = f"UPDATE organizations SET {', '.join(fields)} WHERE companyid = %s"
            
            with conn.cursor() as cur:
                cur.execute(query, values)
                conn.commit()
            return True
        except Exception as e:
             conn.rollback()
             print(f"Error updating organization: {e}")
             raise

    def delete_organization(self, companyid: str) -> bool:
        """
        Delete organization and related data (SaaS cleanup)
        """
        conn = self.get_connection()
        try:
            # 1. Delete organization
            with conn.cursor() as cur:
                cur.execute("DELETE FROM organizations WHERE companyid = %s", (companyid,))
                
                # 2. Optional: Delete or deactivate users (depending on policy)
                # For now, let's just mark them inactive to preserve history? 
                # Or delete if it's a hard delete request. Let's do hard delete for now as requested.
                cur.execute("DELETE FROM user_data WHERE companyid = %s", (companyid,))
                cur.execute("DELETE FROM technician_data WHERE companyid = %s", (companyid,))
                
                conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            print(f"Error deleting organization: {e}")
            raise
    
    # ========== Ticket Update Methods ==========
    
    def update_ticket_status(self, ticket_number: str, new_status: str, tech_id: Optional[str] = None) -> bool:
        """
        Update ticket status with automatic date field updates
        
        Args:
            ticket_number: Ticket number to update
            new_status: New status value
            tech_id: Technician ID (optional)
        
        Returns:
            True if successful, False otherwise
        """
        from datetime import datetime
        conn = self.get_connection()
        
        try:
            # Build update fields based on status
            update_fields = ["status = %s"]
            params = [new_status]
            
            # Auto-update date fields based on status
            if new_status == "In Progress":
                # Check if firstresponsedatetime is already set
                check_query = "SELECT firstresponsedatetime FROM new_tickets WHERE ticketnumber = %s"
                result = self.execute_query(check_query, (ticket_number,))
                if result and not result[0].get('firstresponsedatetime'):
                    update_fields.append("firstresponsedatetime = %s")
                    params.append(datetime.now())
            
            elif new_status == "Closed":
                update_fields.extend([
                    "lastactivitydate = %s",
                    "resolveddatetime = %s",
                    "completeddate = %s"
                ])
                now = datetime.now()
                params.extend([now, now, now])
            
            # Update assigned technician if provided
            if tech_id:
                update_fields.append("assigned_tech_id = %s")
                params.append(tech_id)
            
            # Add ticket_number to params
            params.append(ticket_number)
            
            # Build and execute update query
            update_query = f"""
                UPDATE new_tickets 
                SET {', '.join(update_fields)}
                WHERE ticketnumber = %s
            """
            
            with conn.cursor() as cur:
                cur.execute(update_query, params)
                conn.commit()
                
            print(f"✅ Ticket {ticket_number} status updated to: {new_status}")
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"Error updating ticket status: {e}")
            raise
    
    def update_ticket_field(self, ticket_number: str, field: str, value: Any) -> bool:
        """
        Update a specific field in a ticket
        
        Args:
            ticket_number: Ticket number to update
            field: Field name to update
            value: New value for the field
        
        Returns:
            True if successful, False otherwise
        """
        conn = self.get_connection()
        
        # Allowed fields to update (prevent SQL injection)
        allowed_fields = [
            'priority', 'estimatedhours', 'resolutionplandatetime', 
            'assigned_tech_id', 'status', 'resolution'
        ]
        
        if field not in allowed_fields:
            raise ValueError(f"Field '{field}' is not allowed to be updated")
        
        try:
            query = f"UPDATE new_tickets SET {field} = %s WHERE ticketnumber = %s"
            
            with conn.cursor() as cur:
                cur.execute(query, (value, ticket_number))
                conn.commit()
                
            print(f"✅ Ticket {ticket_number} field '{field}' updated to: {value}")
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"Error updating ticket field: {e}")
            raise
    
    # ========== Context Management Methods ==========
    
    def insert_ticket_context(self, context_data: Dict[str, Any]) -> Optional[int]:
        """
        Insert ticket context into tickets_context table
        
        Args:
            context_data: Dictionary containing context fields
            
        Returns:
            Context ID if successful, None otherwise
        """
        conn = self.get_connection()
        try:
            # Prepare columns and values
            columns = []
            values = []
            
            # Map context_data keys to database columns
            field_mapping = {
                'id': 'id',
                'ticket_id': 'id',  # Support both field names
                'ticket_number': 'ticket_number',
                'title': 'title',
                'description': 'description',
                'extracted_text': 'extracted_text',
                'image_analysis': 'image_analysis',
                'table_data_parsed': 'table_data_parsed',
                'entities': 'entities',
                'context_summary': 'context_summary',
                'file_metadata': 'file_metadata',
                'resolved_at': 'resolved_at',
                'resolution_category': 'resolution_category',
                'assigned_technician_id': 'assigned_technician_id',
                'human_feedback': 'human_feedback'
            }
            
            for key, db_column in field_mapping.items():
                if key in context_data and context_data[key] is not None:
                    columns.append(db_column)
                    value = context_data[key]
                    
                    # Convert dicts to JSON for JSONB columns
                    if db_column in ['image_analysis', 'table_data_parsed', 'entities', 'file_metadata', 'human_feedback']:
                        if isinstance(value, (dict, list)):
                            import json
                            value = json.dumps(value)
                    
                    values.append(value)
            
            if not columns:
                print("No valid context data to insert")
                return None
            
            placeholders = ', '.join(['%s'] * len(columns))
            query = f"""
                INSERT INTO tickets_context ({', '.join(columns)})
                VALUES ({placeholders})
                RETURNING context_id
            """
            
            with conn.cursor() as cur:
                cur.execute(query, values)
                context_id = cur.fetchone()[0]
                conn.commit()
                print(f"✅ Ticket context inserted with ID: {context_id}")
                return context_id
                
        except Exception as e:
            conn.rollback()
            print(f"Error inserting ticket context: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def get_ticket_context(self, ticket_number: str) -> Optional[Dict]:
        """
        Retrieve ticket context by ticket number
        
        Args:
            ticket_number: Ticket number
            
        Returns:
            Context dictionary or None
        """
        query = """
            SELECT * FROM tickets_context
            WHERE ticket_number = %s
            ORDER BY created_at DESC
            LIMIT 1
        """
        results = self.execute_query(query, (ticket_number,))
        return results[0] if results else None
    
    def find_similar_contexts(self, ticket_context: Dict[str, Any], limit: int = 10) -> List[Dict]:
        """
        Find similar ticket contexts for reuse
        Uses context summary and entities for matching
        
        Args:
            ticket_context: Current ticket context
            limit: Maximum number of similar contexts to return
            
        Returns:
            List of similar context dictionaries
        """
        # For now, use simple text-based similarity
        # In production, this could use embeddings or more sophisticated matching
        
        query = """
            SELECT tc.*, nt.resolution
            FROM tickets_context tc
            JOIN new_tickets nt ON tc.id = nt.id
            WHERE tc.resolved_at IS NOT NULL
            AND tc.context_summary IS NOT NULL
            ORDER BY tc.created_at DESC
            LIMIT %s
        """
        
        results = self.execute_query(query, (limit * 2,))  # Get more for filtering
        
        if not results:
            return []
        
        # Simple keyword-based similarity (can be enhanced with embeddings)
        current_summary = ticket_context.get('context_summary', '').lower()
        current_entities = ticket_context.get('entities', {})
        
        scored_results = []
        for result in results:
            score = 0
            result_summary = (result.get('context_summary') or '').lower()
            
            # Simple word overlap scoring
            current_words = set(current_summary.split())
            result_words = set(result_summary.split())
            
            if current_words and result_words:
                overlap = len(current_words & result_words)
                score = overlap / len(current_words | result_words)
            
            scored_results.append((score, result))
        
        # Sort by score and return top results
        scored_results.sort(key=lambda x: x[0], reverse=True)
        return [result for score, result in scored_results[:limit] if score > 0.1]
    
    # ========== Attachment Management Methods ==========
    
    def insert_attachment(self, attachment_data: Dict[str, Any]) -> Optional[int]:
        """
        Insert file attachment record
        
        Args:
            attachment_data: Dictionary containing attachment fields
            
        Returns:
            Attachment ID if successful, None otherwise
        """
        conn = self.get_connection()
        try:
            columns = []
            values = []
            
            field_mapping = {
                'id': 'id',
                'ticket_id': 'id',  # Support both field names
                'ticket_number': 'ticket_number',
                'file_name': 'file_name',
                'file_type': 'file_type',
                'file_size': 'file_size',
                'file_path': 'file_path',
                'processed': 'processed',
                'processing_status': 'processing_status',
                'extracted_content': 'extracted_content',
                'processing_error': 'processing_error'
            }
            
            for key, db_column in field_mapping.items():
                if key in attachment_data and attachment_data[key] is not None:
                    columns.append(db_column)
                    value = attachment_data[key]
                    
                    # Convert dict to JSON for extracted_content if needed
                    if db_column == 'extracted_content' and isinstance(value, dict):
                        import json
                        value = json.dumps(value)
                    
                    values.append(value)
            
            if not columns:
                print("No valid attachment data to insert")
                return None
            
            placeholders = ', '.join(['%s'] * len(columns))
            query = f"""
                INSERT INTO ticket_attachments ({', '.join(columns)})
                VALUES ({placeholders})
                RETURNING attachment_id
            """
            
            with conn.cursor() as cur:
                cur.execute(query, values)
                attachment_id = cur.fetchone()[0]
                conn.commit()
                print(f"✅ Attachment inserted with ID: {attachment_id}")
                return attachment_id
                
        except Exception as e:
            conn.rollback()
            print(f"Error inserting attachment: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def get_attachments(self, ticket_number: str) -> List[Dict]:
        """
        Retrieve all attachments for a ticket
        
        Args:
            ticket_number: Ticket number
            
        Returns:
            List of attachment dictionaries
        """
        query = """
            SELECT * FROM ticket_attachments
            WHERE ticket_number = %s
            ORDER BY uploaded_at ASC
        """
        results = self.execute_query(query, (ticket_number,))
        return results if results else []
    
    def update_attachment_processing(
        self,
        attachment_id: int,
        status: str,
        extracted_content: Optional[str] = None,
        error: Optional[str] = None
    ) -> bool:
        """
        Update attachment processing status
        
        Args:
            attachment_id: Attachment ID
            status: Processing status (pending, processing, completed, failed)
            extracted_content: Extracted content (JSON string or dict)
            error: Error message if failed
            
        Returns:
            True if successful
        """
        conn = self.get_connection()
        try:
            update_fields = ["processing_status = %s", "processed = %s"]
            params = [status, status == 'completed']
            
            if extracted_content is not None:
                update_fields.append("extracted_content = %s")
                if isinstance(extracted_content, dict):
                    import json
                    extracted_content = json.dumps(extracted_content)
                params.append(extracted_content)
            
            if error is not None:
                update_fields.append("processing_error = %s")
                params.append(error)
            
            params.append(attachment_id)
            
            query = f"""
                UPDATE ticket_attachments
                SET {', '.join(update_fields)}
                WHERE attachment_id = %s
            """
            
            with conn.cursor() as cur:
                cur.execute(query, params)
                conn.commit()
            
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"Error updating attachment processing: {e}")
            raise
    
    # ========== Feedback Management Methods ==========
    
    def insert_feedback(self, feedback_data: Dict[str, Any]) -> Optional[int]:
        """
        Insert human feedback for RLHF
        
        Args:
            feedback_data: Dictionary containing feedback fields
            
        Returns:
            Feedback ID if successful, None otherwise
        """
        conn = self.get_connection()
        try:
            columns = []
            values = []
            
            field_mapping = {
                'id': 'id',
                'ticket_id': 'id',  # Support both field names
                'ticket_number': 'ticket_number',
                'feedback_type': 'feedback_type',
                'is_correct': 'is_correct',
                'rating': 'rating',
                'correction_data': 'correction_data',
                'comments': 'comments',
                'technician_id': 'technician_id'
            }
            
            for key, db_column in field_mapping.items():
                if key in feedback_data and feedback_data[key] is not None:
                    columns.append(db_column)
                    value = feedback_data[key]
                    
                    # Convert dict to JSON for correction_data
                    if db_column == 'correction_data' and isinstance(value, dict):
                        import json
                        value = json.dumps(value)
                    
                    values.append(value)
            
            if not columns:
                print("No valid feedback data to insert")
                return None
            
            placeholders = ', '.join(['%s'] * len(columns))
            query = f"""
                INSERT INTO feedback_data ({', '.join(columns)})
                VALUES ({placeholders})
                RETURNING feedback_id
            """
            
            with conn.cursor() as cur:
                cur.execute(query, values)
                feedback_id = cur.fetchone()[0]
                conn.commit()
                print(f"✅ Feedback inserted with ID: {feedback_id}")
                return feedback_id
                
        except Exception as e:
            conn.rollback()
            print(f"Error inserting feedback: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def get_feedback_for_training(self, limit: int = 1000) -> List[Dict]:
        """
        Retrieve feedback data for model training
        
        Args:
            limit: Maximum number of feedback records to retrieve
            
        Returns:
            List of feedback dictionaries
        """
        query = """
            SELECT fd.*, tc.context_summary, tc.entities, nt.title, nt.description
            FROM feedback_data fd
            JOIN tickets_context tc ON fd.id = tc.id
            JOIN new_tickets nt ON fd.id = nt.id
            ORDER BY fd.created_at DESC
            LIMIT %s
        """
        results = self.execute_query(query, (limit,))
        return results if results else []
    
    # ========== Ticket Communications Methods ==========
    
    def insert_ticket_communication(self, comm_data: Dict[str, Any]) -> Optional[int]:
        """
        Insert a communication message for a ticket
        
        Args:
            comm_data: Dictionary containing communication fields
                - ticket_number (required)
                - sender_type (required): 'user', 'technician', or 'system'
                - sender_id (required)
                - message_text (required)
                - message_type (optional): 'text', 'system', 'status_update'
        
        Returns:
            Message ID if successful, None otherwise
        """
        conn = self.get_connection()
        try:
            required_fields = ['ticket_number', 'sender_type', 'sender_id', 'message_text']
            for field in required_fields:
                if field not in comm_data:
                    raise ValueError(f"Missing required field: {field}")
            
            query = """
                INSERT INTO ticket_communications 
                (ticket_number, sender_type, sender_id, message_text, message_type)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING message_id
            """
            
            with conn.cursor() as cur:
                cur.execute(query, (
                    comm_data['ticket_number'],
                    comm_data['sender_type'],
                    comm_data['sender_id'],
                    comm_data['message_text'],
                    comm_data.get('message_type', 'text')
                ))
                message_id = cur.fetchone()[0]
                conn.commit()
                print(f"✅ Communication message inserted with ID: {message_id}")
                return message_id
        except Exception as e:
            conn.rollback()
            print(f"Error inserting communication: {e}")
            raise
    
    def get_ticket_communications(self, ticket_number: str, limit: int = 50) -> List[Dict]:
        """
        Get communication history for a ticket
        
        Args:
            ticket_number: Ticket number
            limit: Maximum number of messages to return
        
        Returns:
            List of communication messages ordered by created_at DESC
        """
        query = """
            SELECT * FROM ticket_communications
            WHERE ticket_number = %s
            ORDER BY created_at DESC
            LIMIT %s
        """
        results = self.execute_query(query, (ticket_number, limit))
        return results if results else []
    
    # ========== Ticket User Feedback Methods ==========
    
    def insert_ticket_feedback(self, feedback_data: Dict[str, Any]) -> Optional[int]:
        """
        Insert user feedback for a resolved/closed ticket
        
        Args:
            feedback_data: Dictionary containing feedback fields
                - ticket_number (required)
                - user_id (required)
                - is_resolved (required): True if satisfied, False if not resolved
                - feedback_text (optional)
                - reopen_reason (optional)
                - previous_tech_id (optional)
        
        Returns:
            Feedback ID if successful, None otherwise
        """
        conn = self.get_connection()
        try:
            required_fields = ['ticket_number', 'user_id', 'is_resolved']
            for field in required_fields:
                if field not in feedback_data:
                    raise ValueError(f"Missing required field: {field}")
            
            query = """
                INSERT INTO ticket_user_feedback 
                (ticket_number, user_id, is_resolved, feedback_text, reopen_reason, previous_tech_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING feedback_id
            """
            
            with conn.cursor() as cur:
                cur.execute(query, (
                    feedback_data['ticket_number'],
                    feedback_data['user_id'],
                    feedback_data['is_resolved'],
                    feedback_data.get('feedback_text'),
                    feedback_data.get('reopen_reason'),
                    feedback_data.get('previous_tech_id')
                ))
                feedback_id = cur.fetchone()[0]
                conn.commit()
                print(f"✅ Ticket feedback inserted with ID: {feedback_id}")
                return feedback_id
        except Exception as e:
            conn.rollback()
            print(f"Error inserting feedback: {e}")
            raise
    
    def reopen_ticket(self, ticket_number: str, reason: str, user_id: str) -> bool:
        """
        Reopen a closed/resolved ticket based on user feedback
        Reassigns to the same technician who previously handled the ticket
        Preserves all communication history
        
        Args:
            ticket_number: Ticket number to reopen
            reason: Reason for reopening
            user_id: User ID who requested reopening
        
        Returns:
            True if successful, False otherwise
        """
        conn = self.get_connection()
        try:

            # Find ticket in new_tickets, resolved_tickets or closed_tickets
            ticket = None
            source_table = None
            assigned_tech_id = None
            
            # Check new_tickets first (e.g. if just marked closed but not moved, or previously failed move)
            query = "SELECT * FROM new_tickets WHERE ticketnumber = %s"
            result = self.execute_query(query, (ticket_number,))
            if result:
                ticket = result[0]
                source_table = "new_tickets"
                assigned_tech_id = ticket.get('assigned_tech_id')
            else:
                for table in ['resolved_tickets', 'closed_tickets']:
                    query = f"SELECT * FROM {table} WHERE ticketnumber = %s"
                    result = self.execute_query(query, (ticket_number,))
                    if result:
                        ticket = result[0]
                        source_table = table
                        assigned_tech_id = ticket.get('assigned_tech_id')
                        break
            
            if not ticket:
                print(f"Ticket {ticket_number} not found in new, resolved or closed tickets")
                return False
            
            # Fallback: Get assigned_tech_id from ticket_assignments history if not in table
            if not assigned_tech_id:
                history_query = """
                    SELECT tech_id FROM ticket_assignments 
                    WHERE ticket_number = %s 
                    ORDER BY assigned_at DESC LIMIT 1
                """
                history_res = self.execute_query(history_query, (ticket_number,))
                if history_res:
                    assigned_tech_id = history_res[0]['tech_id']

            # If already in new_tickets, just update
            if source_table == 'new_tickets':
                print(f"Ticket {ticket_number} found in new_tickets. Updating status directly.")
                update_query = """
                    UPDATE new_tickets 
                    SET status = 'Reopened', resolveddatetime = NULL, completeddate = NULL
                    WHERE ticketnumber = %s
                """
                self.execute_query(update_query, (ticket_number,), fetch=False)
            else:
                # Move ticket back to new_tickets with status "Reopened"
                ticket_dict = dict(ticket)
                ticket_dict['status'] = 'Reopened'
                ticket_dict['resolveddatetime'] = None
                ticket_dict['completeddate'] = None
                
                # Do NOT add assigned_tech_id to ticket_dict as the column may not exist in new_tickets
                # We manage assignment via ticket_assignments table
                if 'assigned_tech_id' in ticket_dict:
                    del ticket_dict['assigned_tech_id']
                
                # Delete from source table
                delete_query = f"DELETE FROM {source_table} WHERE ticketnumber = %s"
                self.execute_query(delete_query, (ticket_number,), fetch=False)
                
                # Insert into new_tickets
                columns = [k for k in ticket_dict.keys() if ticket_dict[k] is not None and k != 'id']
                values = [ticket_dict[k] for k in columns]
                placeholders = ', '.join(['%s'] * len(columns))
                
                insert_query = f"""
                    INSERT INTO new_tickets ({', '.join(columns)})
                    VALUES ({placeholders})
                """
                
                with conn.cursor() as cur:
                    cur.execute(insert_query, values)
                    conn.commit()
            
            # IMPORTANT: Reinstate the assignment record for visibility
            if assigned_tech_id:
                 assignment_data = {
                    'ticket_number': ticket_number,
                    'tech_id': assigned_tech_id,
                    'assignment_reason': f"Reopened by user: {reason}",
                    'status': 'active'
                 }
                 # We insert a new record to show it's active again
                 self.execute_query(
                    "INSERT INTO ticket_assignments (ticket_number, tech_id, assignment_reason, status) VALUES (%s, %s, %s, %s)",
                    (ticket_number, assigned_tech_id, f"Reopened: {reason}", 'active'),
                    fetch=False
                 )
            
            # Update feedback record to mark as reopened
            update_feedback = """
                UPDATE ticket_user_feedback
                SET reopened = TRUE
                WHERE feedback_id = (
                    SELECT feedback_id
                    FROM ticket_user_feedback
                    WHERE ticket_number = %s AND user_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                )
            """
            self.execute_query(update_feedback, (ticket_number, user_id), fetch=False)
            
            # Add system message to communications
            system_message = {
                'ticket_number': ticket_number,
                'sender_type': 'system',
                'sender_id': 'system',
                'message_text': f"Ticket reopened by user. Reason: {reason}",
                'message_type': 'status_update'
            }
            self.insert_ticket_communication(system_message)
            
            print(f"✅ Ticket {ticket_number} reopened and set to 'Reopened' status")
            return True
            
        except Exception as e:
            print(f"Error reopening ticket: {e}")
            self.conn.rollback()
            return False

    def accept_reopened_ticket(self, ticket_number: str) -> bool:
        """
        Technician accepts a reopened ticket, moving it to 'TO DO'
        """
        try:
            # Update status in new_tickets
            query = "UPDATE new_tickets SET status = 'TO DO' WHERE ticketnumber = %s"
            self.execute_query(query, (ticket_number,), fetch=False)
            
            # Log communication
            self.insert_ticket_communication({
                'ticket_number': ticket_number,
                'sender_type': 'system',
                'sender_id': 'system',
                'message_text': "Technician accepted reopen request. Ticket moved to TO DO.",
                'message_type': 'status_update'
            })
            return True
        except Exception as e:
            print(f"Error accepting reopen: {e}")
            return False

    def reject_reopened_ticket(self, ticket_number: str, reason: str, tech_id: str) -> bool:
        """
        Technician rejects a reopened ticket, moving it back to 'Closed'
        """
        conn = self.get_connection()
        try:
            # Get ticket details
            query = "SELECT * FROM new_tickets WHERE ticketnumber = %s"
            result = self.execute_query(query, (ticket_number,))
            if not result:
                return False
            
            ticket = result[0]
            ticket_dict = dict(ticket)
            ticket_dict['status'] = 'Closed'
            from datetime import datetime
            ticket_dict['resolveddatetime'] = datetime.now()
            
            # Remove from new_tickets
            self.execute_query("DELETE FROM new_tickets WHERE ticketnumber = %s", (ticket_number,), fetch=False)
            
            if 'id' in ticket_dict: del ticket_dict['id']
            if 'assigned_tech_id' in ticket_dict: del ticket_dict['assigned_tech_id']
            
            columns = [k for k in ticket_dict.keys() if ticket_dict[k] is not None]
            values = [ticket_dict[k] for k in columns]
            placeholders = ', '.join(['%s'] * len(columns))
            
            insert_query = f"""
                INSERT INTO closed_tickets ({', '.join(columns)})
                VALUES ({placeholders})
            """
            
            with conn.cursor() as cur:
                cur.execute(insert_query, values)
                conn.commit()
            
            # Log communication
            self.insert_ticket_communication({
                'ticket_number': ticket_number,
                'sender_type': 'technician',
                'sender_id': tech_id,
                'message_text': f"Reopen request rejected. Reason: {reason}. Ticket Closed.",
                'message_type': 'status_update'
            })
            
            return True
        except Exception as e:
            conn.rollback()
            print(f"Error rejecting reopen: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    # ========== Queue Management Methods ==========
    
    def get_technician_queue_tickets(
        self, 
        tech_id: Optional[str] = None, 
        status_filter: Optional[str] = None
    ) -> List[Dict]:
        """
        Get queued tickets (not in progress)
        If tech_id is provided, filters by assigned technician
        If tech_id is None, returns all queued tickets
        Maps queueid field to assigned tickets
        
        Args:
            tech_id: Technician ID to filter by (optional)
            status_filter: Additional status filter (optional)
        
        Returns:
            List of queued ticket dictionaries
        """
        try:
            where_clauses = ["status != 'In Progress'"]
            params = []
            
            if tech_id:
                where_clauses.append("assigned_tech_id = %s")
                params.append(tech_id)
            
            if status_filter:
                where_clauses.append("status = %s")
                params.append(status_filter)
            
            where_str = " AND ".join(where_clauses)
            
            query = f"""
                SELECT 
                    ticketnumber, title, description, user_id, createdate,
                    duedatetime, status, priority, issuetype, subissuetype,
                    ticketcategory, tickettype, assigned_tech_id, queueid,
                    estimatedhours, resolutionplandatetime
                FROM new_tickets
                WHERE {where_str}
                ORDER BY createdate DESC
            """
            
            results = self.execute_query(query, tuple(params))
            return results if results else []
            
        except Exception as e:
            print(f"Error getting queue tickets: {e}")
            return []


