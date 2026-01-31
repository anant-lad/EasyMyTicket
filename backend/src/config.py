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
    # Optional: Public host for remote connections (defaults to DB_HOST if not set)
    DB_PUBLIC_HOST = os.getenv('DB_PUBLIC_HOST', DB_HOST)
    
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
    
    # Email Configuration (SMTP for sending)
    SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL', '')
    SUPPORT_EMAIL_APP_PASSWORD = os.getenv('SUPPORT_EMAIL_APP_PASSWORD', '')
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 465))
    
    # IMAP Configuration (for receiving emails to create tickets)
    IMAP_SERVER = os.getenv('IMAP_SERVER', 'imap.gmail.com')
    IMAP_PORT = int(os.getenv('IMAP_PORT', 993))
    IMAP_USE_SSL = os.getenv('IMAP_USE_SSL', 'true').lower() == 'true'
    EMAIL_CHECK_INTERVAL = int(os.getenv('EMAIL_CHECK_INTERVAL', 60))  # seconds
    PROCESSED_EMAIL_FOLDER = os.getenv('PROCESSED_EMAIL_FOLDER', 'Processed')
    AUTO_START_EMAIL_AGENT = os.getenv('AUTO_START_EMAIL_AGENT', 'false').lower() == 'true'
    EMAIL_AGENT_MAX_EMAILS = int(os.getenv('EMAIL_AGENT_MAX_EMAILS', 10))
    
    # File Upload Settings
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    ALLOWED_FILE_TYPES = ['pdf', 'docx', 'doc', 'txt', 'xml', 'html', 'csv', 'xlsx', 'xls', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff']
    UPLOAD_DIRECTORY = os.getenv('UPLOAD_DIRECTORY', './uploads')
    STORAGE_BACKEND = os.getenv('STORAGE_BACKEND', 'local')  # local, s3, azure, gcs
    
    # Context Processing
    ENABLE_IMAGE_OCR = os.getenv('ENABLE_IMAGE_OCR', 'true').lower() == 'true'
    OCR_ENGINE = os.getenv('OCR_ENGINE', 'pytesseract')  # pytesseract, easyocr
    CONTEXT_EMBEDDING_MODEL = os.getenv('CONTEXT_EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
    
    # Transfer Learning
    ENABLE_FEEDBACK_COLLECTION = os.getenv('ENABLE_FEEDBACK_COLLECTION', 'true').lower() == 'true'
    FINE_TUNING_PROVIDER = os.getenv('FINE_TUNING_PROVIDER', 'groq')  # groq, openai
    MIN_FEEDBACK_FOR_TRAINING = int(os.getenv('MIN_FEEDBACK_FOR_TRAINING', '100'))
    
    @classmethod
    def get_db_config(cls, use_public_host: bool = False):
        """
        Get database configuration as dictionary
        
        Args:
            use_public_host: If True, use DB_PUBLIC_HOST instead of DB_HOST (default: False)
        
        Returns:
            Dictionary with database connection parameters
        """
        host = cls.DB_PUBLIC_HOST if use_public_host else cls.DB_HOST
        return {
            'host': host,
            'port': cls.DB_PORT,
            'database': cls.DB_NAME,
            'user': cls.DB_USER,
            'password': cls.DB_PASSWORD
        }
    
    @classmethod
    def validate(cls):
        """Validate required configuration"""
        if not cls.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY environment variable is not set. Please set it in your .env file")
        if not cls.DB_PASSWORD:
            raise ValueError("DB_PASSWORD environment variable is not set. Please set it in your .env file")
        return True

