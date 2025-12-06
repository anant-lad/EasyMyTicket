"""
Database connection module for PostgreSQL
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, List, Dict, Any
from groq import Groq
import json
import re
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from src.config import Config

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
    
    def __init__(self):
        self.db_config = Config.get_db_config()
        self.conn = None
        self.groq_client = None
        self._init_groq()
        self._ensure_tables_exist()
    
    def _init_groq(self):
        """Initialize GROQ client"""
        groq_api_key = Config.GROQ_API_KEY
        
        if not groq_api_key:
            raise ValueError(
                "GROQ_API_KEY environment variable is not set. "
                "Please ensure it's set in your .env file or environment variables."
            )
        
        # Clean up the API key in case it has extra text (handle malformed .env files)
        groq_api_key = groq_api_key.strip()
        if groq_api_key.endswith('GROQ_API_KEY'):
            groq_api_key = groq_api_key[:-12].strip()
        
        try:
            self.groq_client = Groq(api_key=groq_api_key)
            print("✓ GROQ client initialized successfully")
        except Exception as e:
            print(f"ERROR: Failed to initialize GROQ client: {e}")
            raise
    
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
                if fetch:
                    results = cur.fetchall()
                    return [dict(row) for row in results]
                conn.commit()
                return None
        except Exception as e:
            conn.rollback()
            print(f"Error executing query: {e}")
            raise
    
    def call_cortex_llm(self, prompt: str, model: str = 'llama3-8b-8192') -> Optional[Dict]:
        """
        Call GROQ LLM API and parse JSON response
        
        Args:
            prompt: The prompt to send to the LLM
            model: The model to use (default: llama3-8b-8192)
        
        Returns:
            Parsed JSON response as dict or None if failed
        """
        try:
            # Use appropriate model based on input
            # GROQ available models: llama-3.1-8b-instant, llama-3.3-70b-versatile, gemma2-9b-it
            # Note: llama-3.1-70b-versatile and mixtral-8x7b-32768 have been decommissioned
            if '70b' in model.lower() or 'versatile' in model.lower():
                model_name = 'llama-3.3-70b-versatile'  # More capable model for complex tasks
            elif 'mixtral' in model.lower():
                # Mixtral is deprecated, use llama-3.3-70b-versatile instead
                model_name = 'llama-3.3-70b-versatile'
            elif 'llama3' in model.lower() or 'llama' in model.lower() or '8b' in model.lower():
                model_name = 'llama-3.1-8b-instant'  # Fast model for simple tasks
            else:
                model_name = 'llama-3.1-8b-instant'  # Default to fast model
            
            # Add JSON format instruction to prompt
            json_prompt = prompt + "\n\nIMPORTANT: Respond ONLY with valid JSON. Do not include any text before or after the JSON."
            
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
                            "content": "You are a helpful assistant that responds with valid JSON only. Always return properly formatted JSON without any markdown formatting or code blocks."
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
                                    "content": "You are a helpful assistant that responds with valid JSON only. Always return properly formatted JSON without any markdown formatting or code blocks."
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
            print(f"📋 Response preview: {content[:200]}{'...' if len(content) > 200 else ''}")
            
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
            batch_size = min(Config.SEMANTIC_SEARCH_BATCH_SIZE, limit * 10)
            
            query = f"""
                SELECT 
                    ticketnumber, title, description, issuetype, subissuetype,
                    ticketcategory, tickettype, priority, status, createdate,
                    resolveddatetime, resolution
                FROM closed_tickets
                WHERE title IS NOT NULL AND description IS NOT NULL
                ORDER BY createdate DESC
                LIMIT %s
            """
            
            print(f"   📊 Fetching {batch_size} recent tickets for comparison...")
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
                print(f"   ⚠️  No tickets found with similarity >= 0.3, returning top {limit} most recent")
                # Fallback: return most recent tickets if no good matches
                fallback_query = """
                    SELECT 
                        ticketnumber, title, description, issuetype, subissuetype,
                        ticketcategory, tickettype, priority, status, createdate,
                        resolveddatetime, resolution
                    FROM closed_tickets
                    ORDER BY createdate DESC
                    LIMIT %s
                """
                results = self.execute_query(fallback_query, (limit,))
                if results:
                    print(f"   ✅ Found {len(results)} recent tickets (fallback)")
                return results or []
            
        except Exception as e:
            print(f"   ❌ Error finding similar tickets: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to simple query on error
            try:
                fallback_query = """
                    SELECT 
                        ticketnumber, title, description, issuetype, subissuetype,
                        ticketcategory, tickettype, priority, status, createdate,
                        resolveddatetime, resolution
                    FROM closed_tickets
                    ORDER BY createdate DESC
                    LIMIT %s
                """
                results = self.execute_query(fallback_query, (limit,))
                return results or []
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
                where_conditions.append("status = %s")
                params.append(status)
            
            if priority:
                where_conditions.append("priority = %s")
                params.append(priority)
            
            if issuetype:
                where_conditions.append("issuetype = %s")
                params.append(issuetype)
            
            if user_id:
                where_conditions.append("user_id = %s")
                params.append(user_id)
            
            where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
            
            # Get total count
            count_query = f"SELECT COUNT(*) FROM new_tickets WHERE {where_clause}"
            with conn.cursor() as cur:
                cur.execute(count_query, params)
                total = cur.fetchone()[0]
            
            # Get tickets with pagination
            query = f"""
                SELECT 
                    ticketnumber, title, description, user_id, createdate, 
                    duedatetime, status, priority, issuetype, subissuetype,
                    ticketcategory, tickettype, lastactivitydate, resolveddatetime,
                    resolution, companyid, queueid, estimatedhours
                FROM new_tickets
                WHERE {where_clause}
                ORDER BY {order_by} {order_direction}
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
                        print("✓ Database tables exist")
        except Exception as e:
            print(f"Error checking tables: {e}")
            # Try to create tables anyway
            try:
                self._create_tables(conn)
            except Exception as create_error:
                print(f"Error creating tables: {create_error}")
    
    def _create_tables(self, conn):
        """Create all required database tables"""
        sql_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'src', 'database', 'create_tables.sql'
        )
        
        # If SQL file doesn't exist, create tables inline
        if os.path.exists(sql_file):
            with open(sql_file, 'r') as f:
                sql_script = f.read()
        else:
            # Fallback: create tables inline
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
            """
        
        with conn.cursor() as cur:
            cur.execute(sql_script)
            conn.commit()
            print("✓ Database tables created successfully!")
    
    def _create_closed_tickets_table(self, conn):
        """Create closed_tickets table if it doesn't exist"""
        create_table_sql = """
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
        """
        with conn.cursor() as cur:
            cur.execute(create_table_sql)
            conn.commit()
            print("✓ closed_tickets table created successfully!")
    
    def close(self):
        """Close database connection"""
        if self.conn and not self.conn.closed:
            self.conn.close()

