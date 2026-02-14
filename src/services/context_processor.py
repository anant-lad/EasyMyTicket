"""
Context Processor Service
Generates LLM-friendly ticket context from ticket data and processed files
"""
import json
from typing import Dict, Any, List, Optional
from datetime import datetime


class ContextProcessor:
    """
    Processes ticket data and file extractions to create rich, structured context
    optimized for LLM consumption and preventing hallucination
    """
    
    def __init__(self, db_connection=None):
        """
        Initialize context processor
        
        Args:
            db_connection: Database connection for LLM calls
        """
        self.db_connection = db_connection
    
    def generate_ticket_context(
        self,
        ticket_data: Dict[str, Any],
        attachments_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Generate comprehensive ticket context from ticket and file data
        
        Args:
            ticket_data: Ticket information (title, description, etc.)
            attachments_data: List of processed file data
            
        Returns:
            Dictionary containing enriched context
        """
        context = {
            'ticket_id': ticket_data.get('id'),
            'ticket_number': ticket_data.get('ticketnumber'),
            'title': ticket_data.get('title', ''),
            'description': ticket_data.get('description', ''),
            'extracted_text': '',
            'image_analysis': {},
            'table_data_parsed': {},
            'entities': {},
            'context_summary': '',
            'file_metadata': []
        }
        
        # Combine all extracted text from files
        all_text_parts = []
        all_tables = []
        all_images_analysis = []
        
        for attachment in attachments_data:
            # Collect file metadata
            context['file_metadata'].append({
                'file_name': attachment.get('file_name'),
                'file_type': attachment.get('file_type'),
                'file_size': attachment.get('file_size'),
                'processing_status': attachment.get('processing_status', 'unknown')
            })
            
            # Extract processed content
            if attachment.get('extracted_content'):
                try:
                    extracted = json.loads(attachment['extracted_content']) if isinstance(attachment['extracted_content'], str) else attachment['extracted_content']
                    
                    # Collect text
                    if extracted.get('extracted_text'):
                        all_text_parts.append(f"--- From {attachment.get('file_name', 'file')} ---\n{extracted['extracted_text']}")
                    
                    # Collect tables
                    if extracted.get('tables'):
                        all_tables.extend(extracted['tables'])
                    
                    # Collect image analysis
                    if extracted.get('images_analysis'):
                        all_images_analysis.extend(extracted['images_analysis'])
                
                except Exception as e:
                    print(f"Error parsing extracted content: {e}")
        
        # Combine all text
        context['extracted_text'] = '\n\n'.join(all_text_parts)
        
        # Store structured data
        if all_tables:
            context['table_data_parsed'] = {
                'tables': all_tables,
                'count': len(all_tables)
            }
        
        if all_images_analysis:
            context['image_analysis'] = {
                'analyses': all_images_analysis,
                'count': len(all_images_analysis)
            }
        
        # Extract entities using LLM
        context['entities'] = self.extract_entities(
            title=context['title'],
            description=context['description'],
            extracted_text=context['extracted_text']
        )
        
        # Generate context summary
        context['context_summary'] = self.create_context_summary(context)
        
        return context
    
    def extract_entities(
        self,
        title: str,
        description: str,
        extracted_text: str
    ) -> Dict[str, Any]:
        """
        Extract key entities from ticket content using LLM
        
        Args:
            title: Ticket title
            description: Ticket description
            extracted_text: Text extracted from files
            
        Returns:
            Dictionary of extracted entities
        """
        # Combine all text for entity extraction
        combined_text = f"{title}\n\n{description}"
        if extracted_text:
            # Limit extracted text to avoid token limits
            combined_text += f"\n\n{extracted_text[:2000]}"
        
        # If no database connection, return basic extraction
        if not self.db_connection:
            return self._basic_entity_extraction(combined_text)
        
        # Use LLM for entity extraction
        try:
            prompt = f"""
Extract key entities from this IT support ticket. Identify:
1. Product names and software mentioned
2. Version numbers
3. Error codes or error messages
4. Affected systems or components
5. Technical terms and keywords

Ticket Content:
{combined_text}

Respond with JSON in this exact format:
{{
    "products": ["list of products/software"],
    "versions": ["list of version numbers"],
    "error_codes": ["list of error codes"],
    "systems": ["list of affected systems"],
    "keywords": ["list of technical keywords"]
}}
"""
            
            result = self.db_connection.call_cortex_llm(
                prompt=prompt,
                model='llama3-8b',
                json_response=True
            )
            
            if result:
                return result
            else:
                return self._basic_entity_extraction(combined_text)
        
        except Exception as e:
            print(f"Error extracting entities with LLM: {e}")
            return self._basic_entity_extraction(combined_text)
    
    def _basic_entity_extraction(self, text: str) -> Dict[str, Any]:
        """
        Basic entity extraction without LLM (fallback)
        
        Args:
            text: Text to extract entities from
            
        Returns:
            Dictionary of extracted entities
        """
        import re
        
        entities = {
            'products': [],
            'versions': [],
            'error_codes': [],
            'systems': [],
            'keywords': []
        }
        
        # Extract version numbers (e.g., v1.2.3, version 2.0, etc.)
        version_pattern = r'\b(?:v|version|ver\.?)\s*(\d+(?:\.\d+)*)\b'
        versions = re.findall(version_pattern, text, re.IGNORECASE)
        entities['versions'] = list(set(versions))
        
        # Extract error codes (e.g., ERROR-123, ERR_CODE, etc.)
        error_pattern = r'\b(?:error|err)[_\-\s]*[a-z0-9]+\b'
        errors = re.findall(error_pattern, text, re.IGNORECASE)
        entities['error_codes'] = list(set(errors))[:10]  # Limit to 10
        
        # Extract common IT keywords
        common_keywords = [
            'database', 'server', 'network', 'email', 'password', 'login',
            'connection', 'timeout', 'crash', 'slow', 'performance', 'backup',
            'restore', 'update', 'upgrade', 'install', 'configuration'
        ]
        
        text_lower = text.lower()
        found_keywords = [kw for kw in common_keywords if kw in text_lower]
        entities['keywords'] = found_keywords
        
        return entities
    
    def create_context_summary(self, context: Dict[str, Any]) -> str:
        """
        Create a concise summary of the ticket context for efficient LLM consumption
        
        Args:
            context: Full context dictionary
            
        Returns:
            Summary string
        """
        # If no database connection, create basic summary
        if not self.db_connection:
            return self._basic_context_summary(context)
        
        # Use LLM to generate intelligent summary
        try:
            # Prepare content for summarization
            content_parts = [
                f"Title: {context['title']}",
                f"Description: {context['description']}"
            ]
            
            if context.get('extracted_text'):
                # Limit text to avoid token limits
                content_parts.append(f"File Content: {context['extracted_text'][:1500]}")
            
            if context.get('entities'):
                entities = context['entities']
                if entities.get('products'):
                    content_parts.append(f"Products: {', '.join(entities['products'][:5])}")
                if entities.get('error_codes'):
                    content_parts.append(f"Errors: {', '.join(entities['error_codes'][:5])}")
            
            combined_content = '\n'.join(content_parts)
            
            prompt = f"""
Create a concise technical summary of this IT support ticket. Focus on:
- Main issue or request
- Key technical details
- Affected systems/products
- Any error messages or codes

Keep the summary under 200 words and use clear, technical language.

Ticket Information:
{combined_content}

Respond with just the summary text (no JSON, no formatting).
"""
            
            summary = self.db_connection.call_cortex_llm(
                prompt=prompt,
                model='llama3-8b',
                json_response=False
            )
            
            if summary and len(summary.strip()) > 20:
                return summary.strip()
            else:
                return self._basic_context_summary(context)
        
        except Exception as e:
            print(f"Error creating context summary with LLM: {e}")
            return self._basic_context_summary(context)
    
    def _basic_context_summary(self, context: Dict[str, Any]) -> str:
        """
        Create basic context summary without LLM (fallback)
        
        Args:
            context: Full context dictionary
            
        Returns:
            Summary string
        """
        parts = []
        
        # Add title and description
        parts.append(f"Issue: {context['title']}")
        
        # Add file count if any
        if context.get('file_metadata'):
            file_count = len(context['file_metadata'])
            file_types = [f.get('file_type', 'unknown') for f in context['file_metadata']]
            parts.append(f"Attachments: {file_count} file(s) - {', '.join(set(file_types))}")
        
        # Add key entities
        if context.get('entities'):
            entities = context['entities']
            if entities.get('products'):
                parts.append(f"Products: {', '.join(entities['products'][:3])}")
            if entities.get('error_codes'):
                parts.append(f"Errors: {', '.join(entities['error_codes'][:3])}")
        
        return ' | '.join(parts)
    
    def format_for_llm(self, context: Dict[str, Any]) -> str:
        """
        Format context in a structure optimized for LLM consumption
        Prevents hallucination by providing clear, structured information
        
        Args:
            context: Context dictionary
            
        Returns:
            Formatted string for LLM prompts
        """
        formatted_parts = []
        
        # Header
        formatted_parts.append("=== TICKET CONTEXT ===")
        formatted_parts.append(f"Ticket Number: {context.get('ticket_number', 'N/A')}")
        formatted_parts.append(f"Title: {context.get('title', 'N/A')}")
        formatted_parts.append("")
        
        # Description
        formatted_parts.append("Description:")
        formatted_parts.append(context.get('description', 'N/A'))
        formatted_parts.append("")
        
        # Extracted entities
        if context.get('entities'):
            formatted_parts.append("Identified Components:")
            entities = context['entities']
            if entities.get('products'):
                formatted_parts.append(f"  Products: {', '.join(entities['products'])}")
            if entities.get('versions'):
                formatted_parts.append(f"  Versions: {', '.join(entities['versions'])}")
            if entities.get('error_codes'):
                formatted_parts.append(f"  Error Codes: {', '.join(entities['error_codes'])}")
            if entities.get('systems'):
                formatted_parts.append(f"  Systems: {', '.join(entities['systems'])}")
            formatted_parts.append("")
        
        # File information
        if context.get('file_metadata'):
            formatted_parts.append("Attached Files:")
            for file_meta in context['file_metadata']:
                formatted_parts.append(f"  - {file_meta.get('file_name')} ({file_meta.get('file_type')})")
            formatted_parts.append("")
        
        # Extracted text (limited)
        if context.get('extracted_text'):
            formatted_parts.append("Content from Files:")
            # Limit to first 1000 characters
            text = context['extracted_text'][:1000]
            if len(context['extracted_text']) > 1000:
                text += "... [truncated]"
            formatted_parts.append(text)
            formatted_parts.append("")
        
        # Summary
        if context.get('context_summary'):
            formatted_parts.append("Summary:")
            formatted_parts.append(context['context_summary'])
            formatted_parts.append("")
        
        formatted_parts.append("=== END CONTEXT ===")
        
        return '\n'.join(formatted_parts)


# Singleton instance
_context_processor = None

def get_context_processor(db_connection=None) -> ContextProcessor:
    """Get or create context processor instance"""
    global _context_processor
    if _context_processor is None:
        _context_processor = ContextProcessor(db_connection)
    return _context_processor
