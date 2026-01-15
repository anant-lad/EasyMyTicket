"""
Utility for managing OAuth client secrets for technicians
"""
import os
import json
from typing import Optional, Dict

class OAuthManager:
    """Manages storage and retrieval of OAuth client secrets"""
    
    OAUTH_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
        'oauth_cilent'
    )
    
    @classmethod
    def save_client_secret(cls, tech_mail: str, client_data: Dict) -> str:
        """
        Save OAuth client secret to oauth_cilent directory
        
        Args:
            tech_mail: Email of the technician
            client_data: Dictionary containing client secret details
            
        Returns:
            Path to the saved file
        """
        if not os.path.exists(cls.OAUTH_DIR):
            os.makedirs(cls.OAUTH_DIR)
            
        # Get client_id if available to match existing naming pattern
        client_id = client_data.get('web', {}).get('client_id', 'unknown')
        filename = f"client_secret_{client_id}.json"
        
        # Add comment for identification if not present
        if "_comment" not in client_data:
            client_data["_comment"] = f"For Google OAuth {tech_mail}"
            
        file_path = os.path.join(cls.OAUTH_DIR, filename)
        
        with open(file_path, 'w') as f:
            json.dump(client_data, f, indent=4)
            
        return file_path
    
    @classmethod
    def get_client_secrets(cls) -> Dict[str, str]:
        """
        Get mapping of technician emails to their client secret files
        Based on the _comment field in the JSON files
        """
        mapping = {}
        if not os.path.exists(cls.OAUTH_DIR):
            return mapping
            
        for filename in os.listdir(cls.OAUTH_DIR):
            if filename.endswith('.json'):
                path = os.path.join(cls.OAUTH_DIR, filename)
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                        comment = data.get('_comment', '')
                        if "For Google OAuth" in comment:
                            email = comment.replace("For Google OAuth", "").strip()
                            mapping[email] = path
                except:
                    continue
        return mapping
