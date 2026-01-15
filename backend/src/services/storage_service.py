"""
Storage Service for File Upload Management
Handles file validation, storage, and retrieval with support for local and cloud storage
"""
import os
import hashlib
import mimetypes
from datetime import datetime
from typing import Optional, Tuple, BinaryIO
from pathlib import Path
from fastapi import UploadFile, HTTPException
import shutil


class StorageService:
    """
    Manages file storage with validation and security features
    Supports local filesystem storage with future cloud storage extensibility
    """
    
    # Allowed file extensions and their MIME types
    ALLOWED_EXTENSIONS = {
        'pdf': 'application/pdf',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'doc': 'application/msword',
        'txt': 'text/plain',
        'xml': 'application/xml',
        'html': 'text/html',
        'csv': 'text/csv',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'xls': 'application/vnd.ms-excel',
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'gif': 'image/gif',
        'bmp': 'image/bmp',
        'tiff': 'image/tiff'
    }
    
    # Maximum file size: 50MB
    MAX_FILE_SIZE = 50 * 1024 * 1024
    
    def __init__(self, upload_directory: str = './uploads', storage_backend: str = 'local'):
        """
        Initialize storage service
        
        Args:
            upload_directory: Base directory for file uploads
            storage_backend: Storage backend type ('local', 's3', 'azure', 'gcs')
        """
        self.upload_directory = upload_directory
        self.storage_backend = storage_backend
        
        # Create upload directory if it doesn't exist
        if storage_backend == 'local':
            Path(upload_directory).mkdir(parents=True, exist_ok=True)
    
    def validate_file(self, file: UploadFile) -> Tuple[bool, Optional[str]]:
        """
        Validate uploaded file for type and size
        
        Args:
            file: Uploaded file object
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check if file has a filename
        if not file.filename:
            return False, "No filename provided"
        
        # Get file extension
        file_ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        
        # Validate extension
        if file_ext not in self.ALLOWED_EXTENSIONS:
            allowed = ', '.join(self.ALLOWED_EXTENSIONS.keys())
            return False, f"File type '.{file_ext}' not allowed. Allowed types: {allowed}"
        
        # Validate MIME type if available
        if file.content_type:
            expected_mime = self.ALLOWED_EXTENSIONS[file_ext]
            # Some browsers send different MIME types, so we'll be lenient
            if not (file.content_type == expected_mime or 
                    file.content_type.startswith(expected_mime.split('/')[0])):
                # Log warning but don't reject
                print(f"Warning: MIME type mismatch. Expected: {expected_mime}, Got: {file.content_type}")
        
        # Note: We can't check file size here without reading the entire file
        # Size validation will happen during save
        
        return True, None
    
    def _generate_secure_filename(self, original_filename: str, ticket_number: str) -> str:
        """
        Generate a secure filename to prevent path traversal and collisions
        
        Args:
            original_filename: Original uploaded filename
            ticket_number: Ticket number for organization
            
        Returns:
            Secure filename
        """
        # Get file extension
        file_ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else ''
        
        # Create hash of original filename + timestamp for uniqueness
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        hash_input = f"{original_filename}_{timestamp}".encode('utf-8')
        file_hash = hashlib.md5(hash_input).hexdigest()[:12]
        
        # Sanitize base filename (remove special characters)
        base_name = original_filename.rsplit('.', 1)[0] if '.' in original_filename else original_filename
        safe_base = ''.join(c for c in base_name if c.isalnum() or c in ('-', '_'))[:50]
        
        # Construct secure filename: ticket_basename_hash.ext
        secure_name = f"{ticket_number}_{safe_base}_{file_hash}.{file_ext}"
        
        return secure_name
    
    def save_file(self, file: UploadFile, ticket_number: str) -> Tuple[str, int]:
        """
        Save uploaded file to storage
        
        Args:
            file: Uploaded file object
            ticket_number: Ticket number for organization
            
        Returns:
            Tuple of (file_path, file_size)
            
        Raises:
            HTTPException: If file validation or saving fails
        """
        # Validate file
        is_valid, error_msg = self.validate_file(file)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Generate secure filename
        secure_filename = self._generate_secure_filename(file.filename, ticket_number)
        
        # Create ticket-specific subdirectory
        ticket_dir = os.path.join(self.upload_directory, ticket_number)
        Path(ticket_dir).mkdir(parents=True, exist_ok=True)
        
        # Full file path
        file_path = os.path.join(ticket_dir, secure_filename)
        
        try:
            # Save file and track size
            file_size = 0
            with open(file_path, 'wb') as buffer:
                # Read and write in chunks to handle large files
                chunk_size = 1024 * 1024  # 1MB chunks
                while True:
                    chunk = file.file.read(chunk_size)
                    if not chunk:
                        break
                    
                    file_size += len(chunk)
                    
                    # Check size limit
                    if file_size > self.MAX_FILE_SIZE:
                        # Delete partial file
                        os.remove(file_path)
                        raise HTTPException(
                            status_code=413,
                            detail=f"File too large. Maximum size: {self.MAX_FILE_SIZE / (1024*1024):.0f}MB"
                        )
                    
                    buffer.write(chunk)
            
            print(f"✓ File saved: {file_path} ({file_size} bytes)")
            return file_path, file_size
            
        except HTTPException:
            raise
        except Exception as e:
            # Clean up on error
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save file: {str(e)}"
            )
        finally:
            # Reset file pointer for potential reuse
            file.file.seek(0)
    
    def get_file(self, file_path: str) -> Optional[str]:
        """
        Retrieve file from storage
        
        Args:
            file_path: Path to the file
            
        Returns:
            Absolute file path if exists, None otherwise
        """
        if self.storage_backend == 'local':
            if os.path.exists(file_path):
                return os.path.abspath(file_path)
        
        return None
    
    def delete_file(self, file_path: str) -> bool:
        """
        Delete file from storage
        
        Args:
            file_path: Path to the file
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            if self.storage_backend == 'local':
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"✓ File deleted: {file_path}")
                    return True
            return False
        except Exception as e:
            print(f"Error deleting file {file_path}: {e}")
            return False
    
    def get_file_info(self, file_path: str) -> Optional[dict]:
        """
        Get file information
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary with file info or None
        """
        try:
            if os.path.exists(file_path):
                stat = os.stat(file_path)
                return {
                    'path': file_path,
                    'size': stat.st_size,
                    'created': datetime.fromtimestamp(stat.st_ctime),
                    'modified': datetime.fromtimestamp(stat.st_mtime),
                    'mime_type': mimetypes.guess_type(file_path)[0]
                }
        except Exception as e:
            print(f"Error getting file info for {file_path}: {e}")
        
        return None


# Singleton instance
_storage_service = None

def get_storage_service(upload_directory: str = './uploads', storage_backend: str = 'local') -> StorageService:
    """Get or create storage service instance"""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService(upload_directory, storage_backend)
    return _storage_service
