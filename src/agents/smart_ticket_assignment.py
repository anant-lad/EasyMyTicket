"""
Smart Ticket Assignment Agent
Handles intelligent ticket assignment based on skills, availability, and workload
"""
import logging
import re
from datetime import datetime
from typing import Optional, Dict, List, Tuple

from src.database.db_connection import DatabaseConnection
from src.utils.logger import flow

log = logging.getLogger(__name__)


class SmartAssignmentAgent:
    """Agent for smart ticket assignment with skill matching and workload balancing"""
    
    def __init__(self, db_connection: DatabaseConnection):
        self.db_connection = db_connection
        
        # Skill mapping from issue types — skills must be UNIQUE to the category.
        # Do NOT mix skills across categories (e.g. hardware tickets should NOT list
        # 'Network', or a Network tech will win due to lower workload).
        self.issue_type_skills = {
            '4':  ['Hardware', 'Laptop', 'Equipment', 'Repair'],          # Hardware & Equipment
            '5':  ['Software', 'Installation', 'SaaS', 'Application'],    # Software
            '6':  ['Network', 'VPN', 'Remote Access', 'Firewall'],        # Network & Connectivity
            '7':  ['Network', 'Site Survey', 'Assessment'],               # Network Assessment
            '8':  ['Server', 'Administration', 'Database', 'Linux'],      # Server & Infrastructure
            '9':  ['Active Directory', 'Access Control', 'Permissions'],  # Access & Identity
            '11': ['Cloud', 'Email', 'Office 365', 'OneDrive', 'SharePoint'],  # Cloud & Productivity
            '13': ['Backup', 'DATTO', 'Azure', 'Recovery'],              # Backup & DR
            '14': ['Cybersecurity', 'Security', 'Intrusion'],            # Security
            '15': ['Email', 'Password', 'Account'],                      # Email & Accounts
            '18': ['Printer', 'Printing', 'Hardware'],                   # Printing
        }

        # Title keyword → required skill injection.
        # If the ticket title/description contains these words, inject the
        # corresponding skill even if the issuetype mapping didn't include it.
        self.keyword_skill_map = {
            # Hardware keywords
            'touchpad': 'Hardware', 'keyboard': 'Hardware', 'mouse': 'Hardware',
            'trackpad': 'Hardware', 'screen': 'Hardware', 'display': 'Hardware',
            'monitor': 'Hardware', 'hdmi': 'Hardware', 'usb': 'Hardware',
            'camera': 'Hardware', 'webcam': 'Hardware', 'battery': 'Hardware',
            'charger': 'Hardware', 'laptop': 'Hardware', 'hardware': 'Hardware',
            'broken': 'Hardware', 'damaged': 'Hardware', 'replacement': 'Hardware',
            'printer': 'Printer', 'scanner': 'Hardware',
            # Network keywords
            'wifi': 'Network', 'wi-fi': 'Network', 'wireless': 'Network',
            'ethernet': 'Network', 'vpn': 'VPN', 'internet': 'Network',
            'firewall': 'Firewall', 'dns': 'Network', 'ping': 'Network',
            'bluetooth': 'Hardware',
            # Software keywords
            'install': 'Software', 'uninstall': 'Software', 'crash': 'Software',
            'software': 'Software', 'application': 'Software', 'app': 'Software',
            'update': 'Software', 'upgrade': 'Software',
            # Cloud/Email keywords
            'email': 'Email', 'outlook': 'Email', 'office': 'Office 365',
            'teams': 'Cloud', 'onedrive': 'OneDrive', 'sharepoint': 'SharePoint',
            # Security keywords
            'password': 'Password', 'login': 'Account', 'access': 'Access Control',
            'locked': 'Account', 'permission': 'Permissions',
            # Server keywords
            'server': 'Server', 'database': 'Database', 'linux': 'Linux',
            'ssh': 'Linux', 'docker': 'Linux',
        }
    
    def assign_ticket(self, ticket_data: Dict, classification: Dict) -> Optional[str]:
        """
        Assign ticket to the most suitable technician
        
        Args:
            ticket_data: Ticket information
            classification: Classification data with issuetype, subissuetype, etc.
        
        Returns:
            tech_id of assigned technician or None
        """
        ticket_num = ticket_data.get('ticketnumber', '?')
        log.info("ASSIGN:START ticket=%s title=%s",
                 ticket_num, ticket_data.get('title', 'N/A')[:60])

        # Extract required skills from classification + ticket keywords
        required_skills = self._extract_required_skills(classification, ticket_data)
        log.debug("ASSIGN:SKILLS ticket=%s skills=%s", ticket_num, required_skills)

        # Get available technicians
        available_techs = self._get_available_technicians()

        if not available_techs:
            log.warning("ASSIGN:NO_TECHS ticket=%s — no available technicians", ticket_num)
            return None

        log.debug("ASSIGN:TECHS_FOUND ticket=%s count=%d", ticket_num, len(available_techs))

        # Match skills and score technicians
        scored_techs = self._score_technicians(available_techs, required_skills)

        if not scored_techs:
            log.info("ASSIGN:RERANKING ticket=%s — no direct skill match, using semantic reranker",
                     ticket_num)
            scored_techs = self._rerank_technicians(available_techs, ticket_data, required_skills)

        if not scored_techs:
            log.warning("ASSIGN:NO_MATCH ticket=%s — reranker found nothing", ticket_num)
            return None

        # Sort by skill score (desc) then workload (asc)
        scored_techs.sort(key=lambda x: (-x['score'], x['workload']))

        # Assign to best match
        best_match = scored_techs[0]
        tech_id = best_match['tech_id']

        flow(log, "TICKET:ASSIGNED_TECH",
             ticket=ticket_num, tech=best_match['tech_name'],
             score=best_match['score'], workload=best_match['workload'])
        
        # Record assignment
        self._record_assignment(
            ticket_data.get('ticketnumber'),
            tech_id,
            f"Skill score: {best_match['score']}, Workload: {best_match['workload']}",
            best_match['score']
        )
        
        # Update workload
        self._update_workload(tech_id, increment=1)
        
        return tech_id
    
    def _extract_required_skills(self, classification: Dict, ticket_data: Dict = None) -> List[str]:
        """Extract required skills from classification + ticket title/description keywords."""
        skills = []

        def get_value(key):
            val = classification.get(key) or classification.get(key.upper()) or classification.get(key.lower())
            if isinstance(val, dict):
                return val.get('Value') or val.get('value')
            return val

        # Skills from issuetype mapping
        issuetype = str(get_value('issuetype') or '')
        if issuetype in self.issue_type_skills:
            skills.extend(self.issue_type_skills[issuetype])

        # Inject skills from ticket title + description keyword scanning
        if ticket_data:
            text = (
                (ticket_data.get('title') or '') + ' ' +
                (ticket_data.get('description') or '')
            ).lower()
            for kw, skill in self.keyword_skill_map.items():
                if kw in text and skill not in skills:
                    skills.append(skill)

        return list(set(skills))
    
    def _get_available_technicians(self) -> List[Dict]:
        """Get all available technicians"""
        query = """
            SELECT tech_id, tech_name, tech_mail, skills, current_workload, status
            FROM technician_data
            WHERE status IN ('available', 'wfh')
            ORDER BY current_workload ASC;
        """
        
        return self.db_connection.execute_query(query)
    
    def _score_technicians(self, technicians: List[Dict], required_skills: List[str]) -> List[Dict]:
        """Score technicians based on skill matching"""
        scored = []
        
        for tech in technicians:
            tech_skills = tech.get('skills', '') or ''
            score = self._match_skills(required_skills, tech_skills)
            
            if score > 20:  # Minimum threshold — 1 exact match out of 4 skills = 17, lower to capture those
                scored.append({
                    'tech_id': tech['tech_id'],
                    'tech_name': tech['tech_name'],
                    'score': score,
                    'workload': tech['current_workload'] or 0
                })
        
        return scored
    
    def _match_skills(self, required_skills: List[str], tech_skills: str) -> int:
        """
        Fuzzy match skills and return score (0-100)
        
        Args:
            required_skills: List of required skill keywords
            tech_skills: Comma-separated string of technician skills
        
        Returns:
            Match score (0-100)
        """
        if not required_skills or not tech_skills:
            return 0
        
        tech_skills_lower = tech_skills.lower()
        matches = 0
        partial_matches = 0
        
        for skill in required_skills:
            skill_lower = skill.lower()
            
            # Exact match (case-insensitive)
            if skill_lower in tech_skills_lower:
                matches += 1
            else:
                # Partial match (any word from skill)
                words = skill_lower.split()
                for word in words:
                    if len(word) > 3 and word in tech_skills_lower:
                        partial_matches += 1
                        break
        
        # Calculate score
        total_required = len(required_skills)
        exact_score = (matches / total_required) * 70 if total_required > 0 else 0
        partial_score = (partial_matches / total_required) * 30 if total_required > 0 else 0
        
        return int(exact_score + partial_score)
    
    def _rerank_technicians(self, technicians: List[Dict], ticket_data: Dict, required_skills: List[str]) -> List[Dict]:
        """
        Rerank technicians using semantic analysis when no direct skill match
        Uses ticket title/description to find best match
        """
        log.debug("ASSIGN:SEMANTIC_RERANK running")
        
        ticket_text = f"{ticket_data.get('title', '')} {ticket_data.get('description', '')}"
        scored = []
        
        for tech in technicians:
            tech_skills = tech.get('skills', '') or ''
            
            # Calculate semantic similarity between ticket and tech skills
            score = self._semantic_match_score(ticket_text, tech_skills, required_skills)
            
            scored.append({
                'tech_id': tech['tech_id'],
                'tech_name': tech['tech_name'],
                'score': score,
                'workload': tech['current_workload'] or 0
            })
        
        # Return at least top candidates
        scored.sort(key=lambda x: (-x['score'], x['workload']))
        return scored[:5]  # Top 5 candidates
    
    def _semantic_match_score(self, ticket_text: str, tech_skills: str, required_skills: List[str]) -> int:
        """
        Calculate semantic match score.
        Score is based on how many of the TICKET's meaningful words appear in the
        tech's skill list — not the other way around, which would penalise techs
        with broader skill sets.
        """
        if not tech_skills:
            return 10

        ticket_lower = ticket_text.lower()
        skills_lower = tech_skills.lower()

        common_words = {
            'and', 'the', 'for', 'with', 'this', 'that', 'from', 'have', 'has',
            'not', 'are', 'was', 'but', 'its', 'or', 'is', 'in', 'on', 'at',
            'to', 'a', 'an', 'it', 'my', 'me', 'we', 'be', 'do', 'no',
        }

        skill_words  = set(re.findall(r'\w+', skills_lower))  - common_words
        ticket_words = set(re.findall(r'\w+', ticket_lower))  - common_words

        # How many of the ticket's words appear in tech's skills?
        overlap = len(skill_words.intersection(ticket_words))
        total_ticket_words = len(ticket_words) if ticket_words else 1
        base_score = int((overlap / total_ticket_words) * 60) if overlap > 0 else 10

        # Boost for each required skill that matches tech skills
        boost = 0
        for req_skill in required_skills:
            if req_skill.lower() in skills_lower:
                boost += 15  # Stronger per-skill boost (was 10)

        return min(base_score + boost, 100)
    
    def _record_assignment(self, ticket_number: str, tech_id: str, reason: str, score: int):
        """Record assignment in ticket_assignments table"""
        query = """
            INSERT INTO ticket_assignments 
            (ticket_number, tech_id, assignment_reason, skill_match_score)
            VALUES (%s, %s, %s, %s);
        """
        
        self.db_connection.execute_query(
            query, 
            (ticket_number, tech_id, reason, score),
            fetch=False
        )
    
    def _update_workload(self, tech_id: str, increment: int = 1):
        """Update technician's current workload"""
        query = """
            UPDATE technician_data
            SET current_workload = COALESCE(current_workload, 0) + %s,
                no_tickets_assigned = COALESCE(no_tickets_assigned, 0) + %s
            WHERE tech_id = %s;
        """
        
        self.db_connection.execute_query(query, (increment, increment if increment > 0 else 0, tech_id), fetch=False)
    
    def decrement_workload(self, tech_id: str):
        """Decrement workload when ticket is resolved"""
        query = """
            UPDATE technician_data
            SET current_workload = GREATEST(COALESCE(current_workload, 0) - 1, 0),
                solved_tickets = COALESCE(solved_tickets, 0) + 1
            WHERE tech_id = %s;
        """
        
        self.db_connection.execute_query(query, (tech_id,), fetch=False)
        log.debug("ASSIGN:WORKLOAD_DECREMENT tech=%s", tech_id)
    
    def get_assignment_history(self, ticket_number: str) -> List[Dict]:
        """Get assignment history for a ticket"""
        query = """
            SELECT ta.*, td.tech_name, td.tech_mail
            FROM ticket_assignments ta
            JOIN technician_data td ON ta.tech_id = td.tech_id
            WHERE ta.ticket_number = %s
            ORDER BY ta.assigned_at DESC;
        """
        
        return self.db_connection.execute_query(query, (ticket_number,))
