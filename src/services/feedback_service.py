"""
Feedback Service for RLHF (Reinforcement Learning from Human Feedback)
Collects and manages human feedback on ticket classifications, assignments, and resolutions
"""
from typing import Dict, Any, Optional, List
from src.database.db_connection import DatabaseConnection


class FeedbackService:
    """
    Manages feedback collection for continuous model improvement
    """
    
    def __init__(self, db_connection: DatabaseConnection):
        """
        Initialize feedback service
        
        Args:
            db_connection: Database connection instance
        """
        self.db_connection = db_connection
    
    def record_classification_feedback(
        self,
        ticket_number: str,
        is_correct: bool,
        correction_data: Optional[Dict[str, Any]] = None,
        technician_id: Optional[str] = None,
        comments: Optional[str] = None
    ) -> Optional[int]:
        """
        Record feedback on ticket classification
        
        Args:
            ticket_number: Ticket number
            is_correct: Whether the classification was correct
            correction_data: What the correct classification should be
            technician_id: ID of technician providing feedback
            comments: Additional comments
            
        Returns:
            Feedback ID if successful
        """
        feedback_data = {
            'ticket_number': ticket_number,
            'feedback_type': 'classification',
            'is_correct': is_correct,
            'correction_data': correction_data,
            'technician_id': technician_id,
            'comments': comments
        }
        
        return self.db_connection.insert_feedback(feedback_data)
    
    def record_assignment_feedback(
        self,
        ticket_number: str,
        is_correct: bool,
        correct_tech_id: Optional[str] = None,
        technician_id: Optional[str] = None,
        comments: Optional[str] = None
    ) -> Optional[int]:
        """
        Record feedback on ticket assignment
        
        Args:
            ticket_number: Ticket number
            is_correct: Whether the assignment was correct
            correct_tech_id: Who should have been assigned
            technician_id: ID of technician providing feedback
            comments: Additional comments
            
        Returns:
            Feedback ID if successful
        """
        correction_data = None
        if correct_tech_id:
            correction_data = {'correct_tech_id': correct_tech_id}
        
        feedback_data = {
            'ticket_number': ticket_number,
            'feedback_type': 'assignment',
            'is_correct': is_correct,
            'correction_data': correction_data,
            'technician_id': technician_id,
            'comments': comments
        }
        
        return self.db_connection.insert_feedback(feedback_data)
    
    def record_resolution_feedback(
        self,
        ticket_number: str,
        rating: int,
        technician_id: Optional[str] = None,
        comments: Optional[str] = None
    ) -> Optional[int]:
        """
        Record feedback on resolution quality
        
        Args:
            ticket_number: Ticket number
            rating: Quality rating (1-5)
            technician_id: ID of technician providing feedback
            comments: Additional comments
            
        Returns:
            Feedback ID if successful
        """
        if rating < 1 or rating > 5:
            raise ValueError("Rating must be between 1 and 5")
        
        feedback_data = {
            'ticket_number': ticket_number,
            'feedback_type': 'resolution',
            'rating': rating,
            'technician_id': technician_id,
            'comments': comments
        }
        
        return self.db_connection.insert_feedback(feedback_data)
    
    def get_feedback_stats(self) -> Dict[str, Any]:
        """
        Get statistics on collected feedback
        
        Returns:
            Dictionary with feedback statistics
        """
        query = """
            SELECT 
                feedback_type,
                COUNT(*) as total_count,
                SUM(CASE WHEN is_correct = true THEN 1 ELSE 0 END) as correct_count,
                AVG(CASE WHEN rating IS NOT NULL THEN rating ELSE NULL END) as avg_rating
            FROM feedback_data
            GROUP BY feedback_type
        """
        
        results = self.db_connection.execute_query(query)
        
        stats = {
            'total_feedback': 0,
            'by_type': {}
        }
        
        if results:
            for row in results:
                feedback_type = row['feedback_type']
                stats['by_type'][feedback_type] = {
                    'total': row['total_count'],
                    'correct': row.get('correct_count', 0),
                    'avg_rating': float(row['avg_rating']) if row.get('avg_rating') else None
                }
                stats['total_feedback'] += row['total_count']
        
        return stats
    
    def export_training_data(self, format: str = 'jsonl', limit: int = 1000) -> List[Dict[str, Any]]:
        """
        Export feedback data for model training
        
        Args:
            format: Export format ('jsonl', 'json')
            limit: Maximum number of records to export
            
        Returns:
            List of training data records
        """
        feedback_records = self.db_connection.get_feedback_for_training(limit=limit)
        
        training_data = []
        for record in feedback_records:
            training_record = {
                'ticket_number': record.get('ticket_number'),
                'title': record.get('title'),
                'description': record.get('description'),
                'context_summary': record.get('context_summary'),
                'entities': record.get('entities'),
                'feedback_type': record.get('feedback_type'),
                'is_correct': record.get('is_correct'),
                'rating': record.get('rating'),
                'correction_data': record.get('correction_data'),
                'comments': record.get('comments')
            }
            training_data.append(training_record)
        
        return training_data


# Singleton instance
_feedback_service = None

def get_feedback_service(db_connection: DatabaseConnection) -> FeedbackService:
    """Get or create feedback service instance"""
    global _feedback_service
    if _feedback_service is None:
        _feedback_service = FeedbackService(db_connection)
    return _feedback_service
