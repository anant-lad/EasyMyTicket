
import bcrypt

def verify_password(plain_password, hashed_password):
    """
    Verify a plain password against a hash using bcrypt directly.
    Handles both string and byte inputs and legacy plain text checks.
    """
    if not hashed_password:
        return False
        
    # Check if it's a legacy plain text password (doesn't start with $2)
    # bcrypt hashes start with $2a$, $2b$, or $2y$
    if not hashed_password.startswith("$2"):
        return plain_password == hashed_password

    # Convert strings to bytes for bcrypt
    if isinstance(plain_password, str):
        plain_password = plain_password.encode('utf-8')
    if isinstance(hashed_password, str):
        hashed_password = hashed_password.encode('utf-8')
        
    try:
        return bcrypt.checkpw(plain_password, hashed_password)
    except ValueError:
        # Handle invalid hash formats gracefully
        return False

def get_password_hash(password):
    """
    Hash a password using bcrypt
    """
    if isinstance(password, str):
        password = password.encode('utf-8')
        
    # Generate salt and hash
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password, salt).decode('utf-8')
