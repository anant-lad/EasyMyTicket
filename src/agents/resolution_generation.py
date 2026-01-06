"""
Resolution Generation Agent
Generates resolution steps for tickets based on similar historical tickets
"""
from typing import Optional, Dict, List
import json
from src.database.db_connection import DatabaseConnection


class ResolutionGenerationAgent:
    """Agent for generating resolution steps based on similar tickets"""
    
    def __init__(self, db_connection: DatabaseConnection):
        self.db_connection = db_connection
    
    def generate_resolution(
        self,
        ticket_data: Dict,
        extracted_metadata: Dict,
        similar_tickets: List[Dict],
        model: str = 'llama-3.3-70b-versatile'
    ) -> Optional[str]:
        """
        Generate resolution steps for a ticket based on similar historical tickets
        
        Args:
            ticket_data: Current ticket data (title, description, etc.)
            extracted_metadata: Extracted metadata from intake agent
            similar_tickets: List of similar historical tickets with resolutions
            model: LLM model to use for generation
        
        Returns:
            Generated resolution steps as a formatted string, or None if failed
        """
        print("\n" + "="*80)
        print("🔧 RESOLUTION GENERATION - Starting")
        print("="*80)
        print(f"📝 Ticket Title: {ticket_data.get('title', 'N/A')}")
        print(f"🤖 Model: {model}")
        print(f"📊 Similar Tickets with Resolutions: {len([t for t in similar_tickets if t.get('resolution')])}")
        print("-"*80)
        
        # Filter similar tickets that have resolutions
        tickets_with_resolutions = [
            ticket for ticket in similar_tickets 
            if ticket.get('resolution') and ticket.get('resolution').strip()
        ]
        
        if not tickets_with_resolutions:
            print("⚠️  No similar tickets with resolutions found, generating generic resolution...")
            return self._generate_generic_resolution(ticket_data, extracted_metadata, model)
        
        print(f"✅ Found {len(tickets_with_resolutions)} similar tickets with resolutions")
        print("-"*80)
        print("📤 Sending resolution generation prompt to LLM...")
        
        # Build prompt with similar tickets' resolutions
        resolution_prompt = self._build_resolution_prompt(
            ticket_data,
            extracted_metadata,
            tickets_with_resolutions
        )
        
        print(f"📋 Prompt length: {len(resolution_prompt)} characters")
        
        # Call LLM to generate resolution
        generated_resolution = self.db_connection.call_cortex_llm(resolution_prompt, model=model)
        
        if not generated_resolution:
            print("❌ LLM resolution generation failed, using fallback method")
            return self._generate_fallback_resolution(ticket_data, extracted_metadata, tickets_with_resolutions)
        
        # Extract resolution text from LLM response
        resolution_text = self._extract_resolution_text(generated_resolution)
        
        if resolution_text:
            print("✅ Resolution generated successfully!")
            print(f"📝 Resolution length: {len(resolution_text)} characters")
            print(f"📊 Number of steps: {resolution_text.count('Step') or resolution_text.count('step')}")
            print("\n" + "-"*80)
            print("📋 GENERATED RESOLUTION STEPS:")
            print("-"*80)
            # Print resolution with proper formatting
            print(resolution_text)
            print("-"*80)
            print("="*80 + "\n")
            return resolution_text
        else:
            print("⚠️  Could not extract resolution from LLM response, using fallback")
            fallback_resolution = self._generate_fallback_resolution(ticket_data, extracted_metadata, tickets_with_resolutions)
            # Display fallback resolution too
            print("\n" + "-"*80)
            print("📋 GENERATED RESOLUTION STEPS (Fallback):")
            print("-"*80)
            print(fallback_resolution)
            print("-"*80)
            print("="*80 + "\n")
            return fallback_resolution
    
    def _build_resolution_prompt(
        self,
        ticket_data: Dict,
        extracted_metadata: Dict,
        similar_tickets: List[Dict]
    ) -> str:
        """Build the prompt for resolution generation"""
        
        # Limit number of similar tickets to avoid token limits
        MAX_SIMILAR_TICKETS = 5
        
        prompt = f"""
        You are an expert IT support resolution engineer. Generate a highly technical, step-by-step resolution for a new support ticket.
        
        **Target Ticket:**
        Title: {ticket_data.get('title', 'N/A')}
        Description: {ticket_data.get('description', 'N/A')}
        Main Issue: {extracted_metadata.get('main_issue', 'N/A')}
        Affected System: {extracted_metadata.get('affected_system', 'N/A')}
        
        **Reference Historical Tickets:**
        """
        
        for i, ticket in enumerate(similar_tickets[:MAX_SIMILAR_TICKETS], 1):
            prompt += f"\nHistorical Ticket {i}: {ticket.get('title')}\nResolution: {ticket.get('resolution')}\n"
            
        prompt += """
        **Instructions:**
        1. Analyze the specific problem. Be precise.
        2. Provide approximately 10 actionable, technical steps.
        3. Include specific commands (bash, powershell, etc.) or configuration paths.
        4. Focus ONLY on the described issue.
        
        **Output Format:**
        Return a JSON object with a single key "steps" containing a list of strings.
        Example: {"steps": ["Step 1: ...", "Step 2: ..."]}
        """
        return prompt
        
        return prompt
    
    def _extract_resolution_text(self, llm_response: Dict) -> Optional[str]:
        """
        Extract resolution text from LLM response
        
        Handles various response formats:
        - Direct string in 'resolution' key
        - String in 'text' key
        - String in 'content' key
        - List of step dictionaries in 'resolution_steps' key
        - Direct string value
        """
        if isinstance(llm_response, str):
            return llm_response.strip()
        
        if isinstance(llm_response, dict):
            # Try common keys
            for key in ['resolution', 'text', 'content', 'steps', 'resolution_steps', 'output']:
                if key in llm_response:
                    value = llm_response[key]
                    if isinstance(value, str):
                        return value.strip()
                    elif isinstance(value, list):
                        # Handle list of step dictionaries
                        if len(value) > 0 and isinstance(value[0], dict):
                            # Format: [{"step": 1, "description": "..."}, ...]
                            steps = []
                            for item in value:
                                if isinstance(item, dict):
                                    step_num = item.get('step', item.get('number', len(steps) + 1))
                                    desc = item.get('description', item.get('text', item.get('action', str(item))))
                                    steps.append(f"Step {step_num}: {desc}")
                            return '\n'.join(steps).strip()
                        else:
                            # If it's a list of strings, join with newlines
                            return '\n'.join(str(item) for item in value).strip()
            
            # If no common key found, try to find any string value
            for value in llm_response.values():
                if isinstance(value, str) and len(value) > 50:  # Likely the resolution
                    return value.strip()
        
        return None
    
    def _generate_fallback_resolution(
        self,
        ticket_data: Dict,
        extracted_metadata: Dict,
        similar_tickets: List[Dict]
    ) -> str:
        """
        Generate a fallback resolution when LLM fails
        Uses patterns from similar tickets' resolutions
        """
        print("🔄 Generating fallback resolution based on similar tickets...")
        
        # Extract common patterns from similar tickets' resolutions
        resolutions = [
            ticket.get('resolution', '') 
            for ticket in similar_tickets[:5] 
            if ticket.get('resolution')
        ]
        
        # Build a technical resolution based on ticket metadata and main issue
        title = ticket_data.get('title', '').lower()
        description = ticket_data.get('description', '').lower()
        combined_text = f"{title} {description}".lower()
        main_issue = extracted_metadata.get('main_issue', '').lower()
        affected_system = extracted_metadata.get('affected_system', '').lower()
        error_messages = extracted_metadata.get('error_messages', '').lower()
        
        resolution_steps = []
        
        # Step 1: Initial verification specific to the issue
        resolution_steps.append(f"Step 1: Verify the specific issue: {extracted_metadata.get('main_issue', 'reproduce the problem described in the ticket')}")
        
        # Generate technical steps based on the main issue
        if any(word in combined_text or word in main_issue for word in ['email', 'outlook', 'exchange', 'mail']):
            resolution_steps.append("Step 2: Check email server connectivity: 'ping [email-server]' or 'telnet [server] 25/143/993'")
            resolution_steps.append("Step 3: Verify email account settings: Check SMTP/IMAP server addresses, ports (587/465 for SMTP, 143/993 for IMAP), and authentication method")
            resolution_steps.append("Step 4: Test email credentials: Attempt manual authentication using 'openssl s_client -connect [server]:993' for IMAP or test via email client")
            resolution_steps.append("Step 5: Check email client logs: Review application logs for authentication errors or connection timeouts")
            resolution_steps.append("Step 6: Verify DNS resolution: 'nslookup [email-server]' to ensure email server hostname resolves correctly")
            resolution_steps.append("Step 7: Check firewall/antivirus: Verify email ports (25, 587, 143, 993) are not blocked")
            resolution_steps.append("Step 8: Test email functionality: Send test email and verify receipt")
            resolution_steps.append("Step 9: If authentication fails, reset email password or regenerate app-specific password")
            resolution_steps.append("Step 10: Verify email sending/receiving works and confirm with user")
            
        elif any(word in combined_text or word in main_issue for word in ['vpn', 'remote', 'anyconnect', 'forticlient']):
            resolution_steps.append("Step 2: Verify VPN server status: check if the VPN gateway is reachable via 'ping [VPN-Gateway]'")
            resolution_steps.append("Step 3: Check VPN client configuration: ensure server address, port, and protocol (SSL/IPsec) are correct")
            resolution_steps.append("Step 4: Verify authentication credentials: test login at the VPN web portal if available")
            resolution_steps.append("Step 5: Review VPN client logs: look for 'Authentication failed' or 'Timeout' errors in the client logs")
            resolution_steps.append("Step 6: Check local internet connection: ensure stable connection bypasses potential local network blocks")
            resolution_steps.append("Step 7: Verify VPN client version: ensure the client software is up-to-date and compatible with the OS")
            resolution_steps.append("Step 8: Update network drivers: ensure the virtual network adapter used by the VPN is functioning correctly")
            resolution_steps.append("Step 9: Disable conflicting software: temporarily turn off third-party firewalls or other VPN clients")
            resolution_steps.append("Step 10: Restart VPN services: restart the VPN agent service and try connecting again")
            
        elif any(word in combined_text or word in main_issue for word in ['network', 'wifi', 'internet', 'connection', 'wireless']):
            resolution_steps.append("Step 2: Check WiFi adapter status: 'nmcli device status' (Linux) or 'netsh wlan show interfaces' (Windows) or 'ifconfig' (macOS)")
            resolution_steps.append("Step 3: Verify WiFi is enabled: 'nmcli radio wifi on' (Linux) or check NetworkManager GUI settings")
            resolution_steps.append("Step 4: Scan for available networks: 'nmcli device wifi list' (Linux) or 'netsh wlan show networks' (Windows)")
            resolution_steps.append("Step 5: Check WiFi driver status: 'lspci | grep -i network' and 'dmesg | grep -i wifi' (Linux) or Device Manager (Windows)")
            resolution_steps.append("Step 6: Verify network manager service: 'systemctl status NetworkManager' (Linux) or check Services (Windows)")
            resolution_steps.append("Step 7: Check connection logs: 'journalctl -u NetworkManager | tail -50' (Linux) or Event Viewer (Windows)")
            resolution_steps.append("Step 8: Attempt connection: 'nmcli device wifi connect [SSID] password [PASSWORD]' (Linux) or connect via GUI")
            resolution_steps.append("Step 9: Verify IP assignment: 'ip addr show' or 'ipconfig' to confirm DHCP assigned IP address")
            resolution_steps.append("Step 10: Test connectivity: 'ping -c 4 8.8.8.8' and 'ping -c 4 google.com' to verify internet access")
            
        elif any(word in combined_text or word in main_issue for word in ['printer', 'print']):
            resolution_steps.append("Step 2: Verify printer connectivity: 'ping [printer-ip]' or check printer status on network")
            resolution_steps.append("Step 3: Check printer driver status: 'lpstat -p' (Linux) or Print Management (Windows) or System Preferences (macOS)")
            resolution_steps.append("Step 4: Verify print queue: 'lpq' (Linux) or check Print Spooler service status (Windows)")
            resolution_steps.append("Step 5: Test printer connection: 'lp -d [printer-name] /etc/passwd' (Linux) or print test page")
            resolution_steps.append("Step 6: Check printer permissions: Verify user has print permissions and printer is shared correctly")
            resolution_steps.append("Step 7: Restart print services: 'systemctl restart cups' (Linux) or restart Print Spooler service (Windows)")
            resolution_steps.append("Step 8: Verify printer configuration: Check printer IP, port settings, and protocol (IPP, LPD, etc.)")
            resolution_steps.append("Step 9: Test print functionality: Send test print job and verify output")
            resolution_steps.append("Step 10: Confirm printing works and verify with user")
            
        elif any(word in combined_text or word in main_issue for word in ['password', 'login', 'access', 'authentication']):
            resolution_steps.append("Step 2: Verify user account status: 'id [username]' (Linux) or 'net user [username]' (Windows)")
            resolution_steps.append("Step 3: Check account lockout status: Review security logs for failed login attempts")
            resolution_steps.append("Step 4: Verify authentication method: Check if using local account, domain account, or SSO")
            resolution_steps.append("Step 5: Test credentials: Attempt login with known good credentials or reset password")
            resolution_steps.append("Step 6: Check password policy: Verify password meets complexity requirements and hasn't expired")
            resolution_steps.append("Step 7: Review authentication logs: 'journalctl -u ssh' (Linux) or Event Viewer Security logs (Windows)")
            resolution_steps.append("Step 8: Reset password if needed: Use appropriate method (passwd, net user, AD tools)")
            resolution_steps.append("Step 9: Verify access permissions: Check user groups and file/directory permissions")
            resolution_steps.append("Step 10: Test login and access: Confirm user can successfully authenticate and access required resources")
            
        else:
            # Generic but still technical steps based on the main issue
            main_issue_text = extracted_metadata.get('main_issue', 'the reported issue')
            resolution_steps.append(f"Step 2: Check system logs for errors related to: {main_issue_text}")
            resolution_steps.append("Step 3: Review application/system logs: 'journalctl -xe' (Linux) or Event Viewer (Windows) or Console.app (macOS)")
            resolution_steps.append("Step 4: Verify system configuration: Check relevant configuration files or registry settings")
            resolution_steps.append("Step 5: Check service status: 'systemctl status [service-name]' (Linux) or Services (Windows)")
            resolution_steps.append("Step 6: Review error messages: Analyze specific error codes or messages mentioned in the ticket")
            resolution_steps.append("Step 7: Verify dependencies: Check if required services, libraries, or components are installed and running")
            resolution_steps.append("Step 8: Test functionality: Reproduce the issue and verify current behavior")
            resolution_steps.append("Step 9: Apply fix: Implement solution based on root cause analysis")
            resolution_steps.append("Step 10: Verify resolution: Confirm the specific issue is resolved and test related functionality")
        
        resolution_text = '\n'.join(resolution_steps)
        print(f"✅ Fallback resolution generated with {len(resolution_steps)} steps")
        return resolution_text
    
    def _generate_generic_resolution(
        self,
        ticket_data: Dict,
        extracted_metadata: Dict,
        model: str
    ) -> str:
        """
        Generate a generic resolution when no similar tickets are available
        """
        print("🔄 Generating generic resolution...")
        
        # Use LLM to generate a technical resolution focused on the main issue
        prompt = f"""
        You are an IT support engineer. Generate a technical, 10-step resolution guide for this ticket:
        
        Title: {ticket_data.get('title', 'N/A')}
        Description: {ticket_data.get('description', 'N/A')}
        Main Issue: {extracted_metadata.get('main_issue', 'N/A')}
        Affected System: {extracted_metadata.get('affected_system', 'N/A')}
        
        **Requirements:**
        - Return ONLY a JSON object: {{"steps": ["Step 1: ...", "Step 2: ..."]}}
        - Be technical and specific.
        - Steps must be logically ordered.
        """
        
        generated = self.db_connection.call_cortex_llm(prompt, model=model)
        resolution_text = self._extract_resolution_text(generated) if generated else None
        
        if resolution_text:
            print("✅ Generic resolution generated successfully!")
            print("\n" + "-"*80)
            print("📋 GENERATED RESOLUTION STEPS:")
            print("-"*80)
            print(resolution_text)
            print("-"*80)
            print("="*80 + "\n")
            return resolution_text
        else:
            # Ultimate fallback
            fallback_resolution = self._generate_fallback_resolution(ticket_data, extracted_metadata, [])
            print("\n" + "-"*80)
            print("📋 GENERATED RESOLUTION STEPS (Fallback):")
            print("-"*80)
            print(fallback_resolution)
            print("-"*80)
            print("="*80 + "\n")
            return fallback_resolution

