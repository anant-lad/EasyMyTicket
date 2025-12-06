"""
Configuration module for the application
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Application configuration"""
    
    # Database configuration
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = int(os.getenv('DB_PORT', 5433))
    DB_NAME = os.getenv('DB_NAME', 'tickets_db')
    DB_USER = os.getenv('DB_USER', 'admin')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')  # Must be set in .env file
    
    # GROQ API configuration
    GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
    
    # Flask/FastAPI configuration
    PORT = int(os.getenv('PORT', 5000))
    HOST = os.getenv('HOST', '0.0.0.0')
    ENVIRONMENT = os.getenv('ENVIRONMENT', 'development')
    
    # Semantic search model
    SEMANTIC_MODEL_NAME = 'all-MiniLM-L6-v2'
    
    # LLM Models
    METADATA_EXTRACTION_MODEL = 'llama-3.1-8b-instant'
    CLASSIFICATION_MODEL = 'llama-3.3-70b-versatile'
    
    # Similarity search settings
    SIMILAR_TICKETS_LIMIT = 20
    SIMILARITY_THRESHOLD = 0.3
    SEMANTIC_SEARCH_BATCH_SIZE = 500
    
    @classmethod
    def get_db_config(cls):
        """Get database configuration as dictionary"""
        return {
            'host': cls.DB_HOST,
            'port': cls.DB_PORT,
            'database': cls.DB_NAME,
            'user': cls.DB_USER,
            'password': cls.DB_PASSWORD
        }
    
    @classmethod
    def validate(cls):
        """Validate required configuration"""
        if not cls.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY environment variable is not set")
        if not cls.DB_PASSWORD:
            raise ValueError("DB_PASSWORD environment variable is not set. Please set it in your .env file")
        return True

