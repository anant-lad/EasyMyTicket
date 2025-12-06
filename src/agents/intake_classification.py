"""
Intake Classification Agent
Handles ticket metadata extraction and classification
"""
from typing import Optional, Dict, List
import json
from collections import Counter
from src.database.db_connection import DatabaseConnection


class IntakeClassificationAgent:
    """Agent for extracting metadata and classifying tickets"""
    
    def __init__(self, db_connection: DatabaseConnection):
        self.db_connection = db_connection
        self.reference_data = self._load_reference_data()
    
    def _load_reference_data(self) -> Dict:
        """
        Load reference data for classification fields
        This maps numeric IDs to human-readable labels
        """
        # These are typical IT support ticket classification values
        # You may need to adjust these based on your actual data
        return {
            "issuetype": {
                "1": "Incident",
                "2": "Request",
                "3": "Problem",
                "4": "Change",
                "11": "Incident"
            },
            "subissuetype": {
                "1": "General",
                "2": "Hardware",
                "3": "Software",
                "4": "Network",
                "5": "Email",
                "6": "Security",
                "11": "General"
            },
            "ticketcategory": {
                "1": "Hardware",
                "2": "Software",
                "3": "Network",
                "4": "Email/Communication",
                "5": "Security",
                "6": "Software/SaaS",
                "7": "Hardware",
                "8": "Network",
                "9": "Email",
                "10": "Security",
                "11": "Not Mentioned",
                "3": "Not Mentioned"
            },
            "tickettype": {
                "1": "Service Request",
                "2": "Incident",
                "3": "Problem",
                "4": "Change Request",
                "5": "Task",
                "11": "Service Request"
            },
            "priority": {
                "1": "Critical",
                "2": "High",
                "3": "Medium",
                "4": "Low",
                "5": "Low"
            },
            "status": {
                "1": "New",
                "2": "In Progress",
                "3": "Resolved",
                "4": "Closed",
                "5": "Open"
            }
        }
    
    def extract_metadata(self, title: str, description: str, model: str = 'llama3-8b') -> Optional[Dict]:
        """
        Extracts structured metadata from the ticket title and description using LLM.

        Args:
            title (str): Ticket title
            description (str): Ticket description
            model (str): LLM model to use

        Returns:
            dict: Extracted metadata or None if failed
        """
        prompt = f"""
        Analyze the following IT support ticket title and description and extract the specified metadata in JSON format.

        Ensure all fields are present. For urgency_level, analyze the impact and urgency based on the issue described.

        Ticket Title: "{title}"

        Ticket Description: "{description}"

        Guidelines for urgency_level assessment:

        - "Critical": System down, security breach, data loss, business-critical functions unavailable

        - "High": Major functionality impaired, multiple users affected, workarounds difficult

        - "Medium": Single user affected, workarounds available, non-critical functions impaired

        - "Low": Minor issues, cosmetic problems, feature requests, general questions

        Guidelines for error_messages extraction:

        - Look for specific error codes, error numbers, or exact error text in quotes

        - Include popup messages, dialog box text, or system-generated messages

        - Examples: "Error 404", "Connection timeout", "Access denied", "File not found"

        - If no specific error message is mentioned, extract any symptoms or failure descriptions

        JSON Schema:

        {{
            "main_issue": "What is the main issue or problem described?",
            "affected_system": "What system or application is affected?",
            "urgency_level": "Assess urgency based on impact and business criticality (Critical, High, Medium, or Low)",
            "error_messages": "Extract any specific error messages, codes, or failure symptoms mentioned in the ticket",
            "technical_keywords": ["list", "of", "technical", "terms", "separated", "by", "comma"],
            "user_actions": "What actions was the user trying to perform when the issue occurred?",
            "resolution_indicators": "What type of resolution approach or common fix might address this issue?",
            "STATUS": "Open"
        }}
        """
        
        print("\n" + "="*80)
        print("🔍 METADATA EXTRACTION - Starting")
        print("="*80)
        print(f"📝 Title: {title}")
        print(f"📄 Description: {description[:200]}{'...' if len(description) > 200 else ''}")
        print(f"🤖 Model: {model}")
        print("-"*80)
        print("📤 Sending prompt to LLM for metadata extraction...")
        
        extracted_data = self.db_connection.call_cortex_llm(prompt, model=model)
        
        if extracted_data:
            extracted_data["STATUS"] = "Open"
            print("✅ Metadata extraction successful!")
            print("📊 Extracted Metadata:")
            print(f"   - Main Issue: {extracted_data.get('main_issue', 'N/A')}")
            print(f"   - Affected System: {extracted_data.get('affected_system', 'N/A')}")
            print(f"   - Urgency Level: {extracted_data.get('urgency_level', 'N/A')}")
            print(f"   - Error Messages: {extracted_data.get('error_messages', 'N/A')}")
            print(f"   - Technical Keywords: {extracted_data.get('technical_keywords', [])}")
            print(f"   - User Actions: {extracted_data.get('user_actions', 'N/A')}")
            print(f"   - Resolution Indicators: {extracted_data.get('resolution_indicators', 'N/A')}")
            print("="*80 + "\n")
        else:
            print("❌ Metadata extraction failed - LLM returned None")
            print("="*80 + "\n")
        
        return extracted_data
    
    def classify_ticket(self, new_ticket_data: Dict, extracted_metadata: Dict,
                       similar_tickets: List[Dict], model: str = None) -> Optional[Dict]:
        """
        Classifies the new ticket (ISSUETYPE, SUBISSUETYPE, TICKETCATEGORY, TICKETTYPE, PRIORITY)
        based on extracted metadata and similar tickets using LLM.

        Args:
            new_ticket_data (dict): New ticket data
            extracted_metadata (dict): Extracted metadata
            similar_tickets (list): List of similar tickets
            model (str): LLM model to use

        Returns:
            dict: Classification data or None if failed
        """
        from src.config import Config
        
        # Use default model if not specified
        if model is None:
            model = Config.CLASSIFICATION_MODEL
        
        # Summarize similar tickets (use lowercase keys to match database columns)
        summary = {}
        field_mapping = {
            "ISSUETYPE": "issuetype",
            "SUBISSUETYPE": "subissuetype", 
            "TICKETCATEGORY": "ticketcategory",
            "TICKETTYPE": "tickettype",
            "PRIORITY": "priority"
        }
        for field_upper, field_lower in field_mapping.items():
            values = [ticket.get(field_lower) for ticket in similar_tickets if ticket.get(field_lower) not in [None, "N/A"]]
            if values:
                most_common, count = Counter(values).most_common(1)[0]
                summary[field_upper] = {"Value": most_common, "Count": count}
        
        summary_str = "\nMost common classification values among similar tickets:\n"
        for field, info in summary.items():
            label = self.reference_data.get(field.lower(), {}).get(str(info["Value"]), "Unknown")
            summary_str += f"{field}: {info['Value']} (Label: {label}, appeared {info['Count']} times)\n"
        
        classification_prompt = f"""
        You are an expert IT support ticket classifier. Analyze the ticket content carefully and classify it based on what the issue is actually about.

        **CRITICAL CLASSIFICATION RULES:**

        1. **Content-First Analysis**: Base your classification PRIMARILY on the ticket title, description, and extracted metadata

        2. **Logical Categorization**:

           - Software applications (Teams, Office, browsers, etc.) → TICKETCATEGORY: Software/SaaS

           - Hardware devices (printers, computers, phones) → TICKETCATEGORY: Hardware

           - Network connectivity, WiFi, internet → TICKETCATEGORY: Network

           - Email, Exchange, Outlook → TICKETCATEGORY: Email/Communication

           - Security, passwords, access → TICKETCATEGORY: Security

        3. **Ignore Misleading Patterns**: Do NOT be influenced by potentially incorrect historical classifications

        **Classification Fields:**

        - **ISSUETYPE** → Type of request (Incident=something broken, Request=asking for something, Problem=recurring issue, Change=modification)

        - **SUBISSUETYPE** → Specific sub-category within the issue type

        - **TICKETCATEGORY** → What system/area is affected (Software, Hardware, Network, Security, etc.)

        - **TICKETTYPE** → Service Request, Incident, Problem, Change Request, or Task

        - **PRIORITY** → Urgency level based on business impact and user-specified priority

        - **STATUS** → Always "Open" for new tickets

        **ANALYSIS STEPS:**

        1. Read the ticket title and description carefully

        2. Identify what system/application/hardware is mentioned

        3. Determine if it's broken (Incident) or a request for something (Request)

        4. Choose the category that matches the affected system

        5. Set appropriate priority based on impact and urgency

        ---

        **New Ticket Information**  

        - **Title:** "{new_ticket_data.get('title', 'N/A')}"  

        - **Description:** "{new_ticket_data.get('description', 'N/A')}"  

        - **Extracted Metadata:** {json.dumps(extracted_metadata, indent=2)}  

        - **Initial Priority (user-given):** "{new_ticket_data.get('priority', 'N/A')}"  

        ---

        **Similar Historical Tickets for Context:**  

        (Use these as references for classification consistency)  

        Consider the following similar historical tickets for classification context:

        """
        
        MAX_SIMILAR_TICKETS_FOR_PROMPT = 15
        
        if similar_tickets:
            for i, ticket in enumerate(similar_tickets[:MAX_SIMILAR_TICKETS_FOR_PROMPT]):
                title = ticket.get('title') or 'N/A'
                title_truncated = title[:100] if isinstance(title, str) else 'N/A'
                classification_prompt += f"""
                --- Similar Ticket {i+1} ---
                Title: {title_truncated}
                ISSUE_TYPE: {ticket.get('issuetype', 'N/A')}
                SUBISSUE_TYPE: {ticket.get('subissuetype', 'N/A')}
                CATEGORY: {ticket.get('ticketcategory', 'N/A')}
                TYPE: {ticket.get('tickettype', 'N/A')}
                PRIORITY: {ticket.get('priority', 'N/A')}
                """
        else:
            classification_prompt += "\nNo similar historical tickets found to provide additional context."
        
        classification_prompt += summary_str
        
        classification_prompt += """

\n\nAvailable Classification Options (Field: {Value: Label, ...}):\n"""
        
        classification_fields = ["issuetype", "subissuetype", "ticketcategory", "tickettype", "priority", "status"]
        for field_name in classification_fields:
            if field_name in self.reference_data:
                options_str = ", ".join([f'"{val}": "{label}"' for val, label in self.reference_data[field_name].items()])
                classification_prompt += f"  {field_name.upper()}: {{{options_str}}}\n"
            else:
                classification_prompt += f"  {field_name.upper()}: No specific options provided.\n"
        
        classification_prompt += """
**CLASSIFICATION INSTRUCTIONS:**

1. **ANALYZE THE TICKET CONTENT FIRST**: Look at the title, description, and extracted metadata to understand what the issue is actually about.

2. **CHOOSE THE CORRECT CATEGORY**: Based on the content analysis:

   - If it mentions software applications (Teams, Office, browsers, etc.) → TICKETCATEGORY should be "Software/SaaS"

   - If it mentions hardware (printers, computers, phones) → TICKETCATEGORY should be "Hardware"

   - If it mentions network/connectivity → TICKETCATEGORY should be "Network"

   - If it mentions email/communication → TICKETCATEGORY should be "Email" or similar

3. **DETERMINE ISSUE TYPE**:

   - If something is broken/not working → ISSUETYPE: "Incident"

   - If user is requesting something → ISSUETYPE: "Request"

4. **USE AVAILABLE OPTIONS**: Select from the provided classification options that best match your analysis.

5. **HISTORICAL CONTEXT**: Use similar tickets only as secondary reference, not as the primary decision factor.

**OUTPUT FORMAT**: Provide classification in JSON format with both Value (numerical ID) and Label from the available options.

JSON Schema:

{
    "ISSUETYPE": { "Value": "numerical_id", "Label": "Descriptive Label" },
    "SUBISSUETYPE": { "Value": "numerical_id", "Label": "Descriptive Label" },
    "TICKETCATEGORY": { "Value": "numerical_id", "Label": "Descriptive Label" },
    "TICKETTYPE": { "Value": "numerical_id", "Label": "Descriptive Label" },
    "STATUS": { "Value": "numerical_id", "Label": "Descriptive Label" },
    "PRIORITY": { "Value": "numerical_id", "Label": "Descriptive Label" }
}
        """
        
        print("\n" + "="*80)
        print("🏷️  TICKET CLASSIFICATION - Starting")
        print("="*80)
        print(f"📝 Ticket Title: {new_ticket_data.get('title', 'N/A')}")
        print(f"🤖 Model: {model}")
        print(f"📊 Similar Tickets Found: {len(similar_tickets)}")
        print("-"*80)
        
        if similar_tickets:
            print("🔍 Similar Tickets Summary:")
            for field, info in summary.items():
                label = self.reference_data.get(field.lower(), {}).get(str(info["Value"]), "Unknown")
                print(f"   - {field}: {info['Value']} ({label}) - appeared {info['Count']} times")
        else:
            print("⚠️  No similar tickets found")
        
        print("-"*80)
        print("📤 Sending classification prompt to LLM...")
        print(f"📋 Prompt length: {len(classification_prompt)} characters")
        
        classified_data = self.db_connection.call_cortex_llm(classification_prompt, model=model)
        
        # Handle case where LLM returns None
        if not classified_data:
            print("❌ LLM classification failed, using intelligent content-based fallback classification")
            classified_data = self._intelligent_fallback_classification(new_ticket_data, extracted_metadata, summary)
            print("🔄 Using fallback classification method")
        else:
            print("✅ Classification successful!")
        
        print("-"*80)
        print("📊 Classification Results:")
        if classified_data:
            for field in ["ISSUETYPE", "SUBISSUETYPE", "TICKETCATEGORY", "TICKETTYPE", "PRIORITY", "STATUS"]:
                if field in classified_data:
                    value = classified_data[field]
                    if isinstance(value, dict):
                        print(f"   - {field}: Value={value.get('Value', 'N/A')}, Label={value.get('Label', 'N/A')}")
                    else:
                        print(f"   - {field}: {value}")
        print("="*80 + "\n")
        
        return classified_data
    
    def _intelligent_fallback_classification(self, new_ticket_data: Dict, 
                                            extracted_metadata: Dict, 
                                            summary: Dict) -> Dict:
        """
        Fallback classification when LLM fails
        Uses content analysis and summary of similar tickets
        """
        title = new_ticket_data.get('title', '').lower()
        description = new_ticket_data.get('description', '').lower()
        combined_text = f"{title} {description}".lower()
        
        # Determine category based on keywords
        if any(word in combined_text for word in ['email', 'outlook', 'exchange', 'mail']):
            category = {"Value": "4", "Label": "Email/Communication"}
        elif any(word in combined_text for word in ['network', 'wifi', 'internet', 'connection', 'vpn']):
            category = {"Value": "3", "Label": "Network"}
        elif any(word in combined_text for word in ['printer', 'computer', 'laptop', 'hardware', 'device']):
            category = {"Value": "1", "Label": "Hardware"}
        elif any(word in combined_text for word in ['software', 'application', 'app', 'teams', 'office']):
            category = {"Value": "6", "Label": "Software/SaaS"}
        elif any(word in combined_text for word in ['password', 'security', 'access', 'login']):
            category = {"Value": "5", "Label": "Security"}
        else:
            category = {"Value": "3", "Label": "Not Mentioned"}
        
        # Determine issue type
        if any(word in combined_text for word in ['broken', 'not working', 'error', 'failed', 'issue', 'problem']):
            issue_type = {"Value": "1", "Label": "Incident"}
        elif any(word in combined_text for word in ['request', 'need', 'want', 'please', 'can you']):
            issue_type = {"Value": "2", "Label": "Request"}
        else:
            issue_type = {"Value": "1", "Label": "Incident"}  # Default to Incident
        
        # Use urgency from metadata if available
        urgency = extracted_metadata.get('urgency_level', 'Medium').lower()
        if urgency == 'critical':
            priority = {"Value": "1", "Label": "Critical"}
        elif urgency == 'high':
            priority = {"Value": "2", "Label": "High"}
        elif urgency == 'low':
            priority = {"Value": "4", "Label": "Low"}
        else:
            priority = {"Value": "3", "Label": "Medium"}
        
        # Use summary for other fields if available
        subissuetype_info = summary.get("SUBISSUETYPE")
        if subissuetype_info and isinstance(subissuetype_info, dict):
            subissuetype = {"Value": str(subissuetype_info.get("Value", "1")), "Label": "General"}
        else:
            subissuetype = {"Value": "1", "Label": "General"}
        
        tickettype_info = summary.get("TICKETTYPE")
        if tickettype_info and isinstance(tickettype_info, dict):
            tickettype = {"Value": str(tickettype_info.get("Value", "1")), "Label": "Service Request"}
        else:
            tickettype = {"Value": "1", "Label": "Service Request"}
        
        return {
            "ISSUETYPE": issue_type,
            "SUBISSUETYPE": subissuetype,
            "TICKETCATEGORY": category,
            "TICKETTYPE": tickettype,
            "STATUS": {"Value": "5", "Label": "Open"},
            "PRIORITY": priority
        }

