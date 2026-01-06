"""
Smart Ticket Assignment Agent
Handles intelligent ticket assignment based on skills, availability, and workload
"""
from typing import Optional, Dict, List, Tuple
from src.database.db_connection import DatabaseConnection
from datetime import datetime
import re


class SmartAssignmentAgent:
    """Agent for smart ticket assignment with skill matching and workload balancing"""
    
    def __init__(self, db_connection: DatabaseConnection):
        self.db_connection = db_connection
        
        # Skill mapping from issue types (from analysis)
        self.issue_type_skills = {
            '11': ['Cloud', 'Email', 'Office 365', 'OneDrive', 'SharePoint', 'Cloud Workspace'],
            '4': ['Hardware', 'Network', 'Assessment'],
            '5': ['Software', 'Installation', 'SaaS'],
            '6': ['Network', 'VPN', 'Remote Access'],
            '7': ['Assessment', 'Network Analysis', 'Site Survey'],
            '8': ['Server', 'Administration', 'Database'],
            '9': ['Active Directory', 'File Permissions', 'Access Control'],
            '13': ['Backup', 'DATTO', 'Azure', 'Backup Management'],
            '14': ['Cybersecurity', 'Intrusion', 'Security'],
            '15': ['Email', 'Security', 'Password'],
            '18': ['Printer', 'Printing', 'Hardware'],
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
        print(f"\n🎯 Starting smart ticket assignment...")
        print(f"   Ticket: {ticket_data.get('title', 'N/A')[:60]}")
        
        # Extract required skills from classification
        required_skills = self._extract_required_skills(classification)
        print(f"   Required skills: {required_skills}")
        
        # Get available technicians
        available_techs = self._get_available_technicians()
        
        if not available_techs:
            print("   ⚠️  No available technicians found")
            return None
        
        print(f"   Found {len(available_techs)} available technicians")
        
        # Match skills and score technicians
        scored_techs = self._score_technicians(available_techs, required_skills)
        
        if not scored_techs:
            print("   ℹ️  No technicians with matching skills, using reranker...")
            # Fallback: Use reranker to find best match
            scored_techs = self._rerank_technicians(available_techs, ticket_data, required_skills)
        
        if not scored_techs:
            print("   ⚠️  No suitable technician found after reranking")
            return None
        
        # Sort by skill score (desc) then workload (asc)
        scored_techs.sort(key=lambda x: (-x['score'], x['workload']))
        
        # Assign to best match
        best_match = scored_techs[0]
        tech_id = best_match['tech_id']
        
        print(f"   ✅ Best match: {best_match['tech_name']} (Score: {best_match['score']}, Workload: {best_match['workload']})")
        
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
    
    def _extract_required_skills(self, classification: Dict) -> List[str]:
        """Extract required skills from classification data"""
        skills = []
        
        # Helper to get value from potentially case-insensitive or nested classification
        def get_value(key):
            val = classification.get(key) or classification.get(key.upper()) or classification.get(key.lower())
            if isinstance(val, dict):
                return val.get('Value') or val.get('value')
            return val

        # Get skills from issuetype
        issuetype = str(get_value('issuetype') or '')
        if issuetype in self.issue_type_skills:
            skills.extend(self.issue_type_skills[issuetype])
        
        # Add generic skills from priority
        priority = str(get_value('priority') or '')
        if priority and priority.lower() in ['high', 'critical', 'urgent', '1']:
            skills.append('Urgent Support')
        
        return list(set(skills))  # Remove duplicates
    
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
            
            if score > 30:  # Minimum threshold
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
        print("   🔄 Applying reranker for best match...")
        
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
        Calculate semantic match score using keyword overlap and tech skills
        """
        if not tech_skills:
            return 20  # Minimum score for available techs
        
        ticket_lower = ticket_text.lower()
        skills_lower = tech_skills.lower()
        
        # Count keyword matches
        skill_words = set(re.findall(r'\w+', skills_lower))
        ticket_words = set(re.findall(r'\w+', ticket_lower))
        
        # Filter out common words
        common_words = {'and', 'the', 'for', 'with', 'this', 'that', 'from', 'have', 'has'}
        skill_words = skill_words - common_words
        ticket_words = ticket_words - common_words
        
        # Calculate overlap
        overlap = len(skill_words.intersection(ticket_words))
        total_skill_words = len(skill_words) if skill_words else 1
        
        base_score = int((overlap / total_skill_words) * 60) if overlap > 0 else 20
        
        # Boost if required skills partially match
        boost = 0
        for req_skill in required_skills:
            if req_skill.lower() in skills_lower:
                boost += 10
        
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
        print(f"   ✅ Decremented workload for {tech_id}")
    
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
