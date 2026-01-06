"""
Picklist Loader Utility
Loads and manages picklist values from CSV for data normalization
"""
import csv
import os
from typing import Dict, Optional, List, Tuple
from pathlib import Path


class PicklistLoader:
    """Loads and manages picklist values from CSV file"""
    
    def __init__(self, csv_path: str = None):
        """
        Initialize picklist loader
        
        Args:
            csv_path: Path to picklist CSV file. If None, uses default path.
        """
        if csv_path is None:
            # Default path relative to project root
            project_root = Path(__file__).parent.parent.parent
            csv_path = project_root / "dataset" / "picklist_values (1).csv"
        
        self.csv_path = csv_path
        self.picklist_data: Dict[str, Dict[str, str]] = {}  # {field: {value: label}}
        self.reverse_lookup: Dict[str, Dict[str, str]] = {}  # {field: {label: value}}
        self._load_picklist()
    
    def _load_picklist(self):
        """Load picklist data from CSV file"""
        if not os.path.exists(self.csv_path):
            raise FileNotFoundError(
                f"Picklist CSV file not found at: {self.csv_path}\n"
                f"Please ensure the file exists or provide a valid path."
            )
        
        print(f"📋 Loading picklist data from: {self.csv_path}")
        
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                field = row.get('Field', '').strip().lower()
                value = row.get('Value', '').strip()
                label = row.get('Label', '').strip()
                
                if not field or not value or not label:
                    continue
                
                # Initialize field dictionaries if not exists
                if field not in self.picklist_data:
                    self.picklist_data[field] = {}
                    self.reverse_lookup[field] = {}
                
                # Store value -> label mapping
                self.picklist_data[field][value] = label
                
                # Store label -> value mapping (case-insensitive for lookup)
                # Handle multiple values mapping to same label by keeping first occurrence
                label_lower = label.lower()
                if label_lower not in self.reverse_lookup[field]:
                    self.reverse_lookup[field][label_lower] = value
        
        # Print summary
        total_fields = len(self.picklist_data)
        total_values = sum(len(values) for values in self.picklist_data.values())
        print(f"✅ Loaded {total_values} picklist values across {total_fields} fields")
        for field, values in self.picklist_data.items():
            print(f"   - {field}: {len(values)} values")
    
    def get_label(self, field: str, value: str) -> Optional[str]:
        """
        Get label for a given field and value
        
        Args:
            field: Field name (e.g., 'issuetype', 'priority')
            value: Value ID (e.g., '1', '2')
        
        Returns:
            Label string or None if not found
        """
        field = field.lower()
        if field in self.picklist_data:
            return self.picklist_data[field].get(str(value))
        return None
    
    def get_value(self, field: str, label: str) -> Optional[str]:
        """
        Get value ID for a given field and label
        
        Args:
            field: Field name (e.g., 'issuetype', 'priority')
            label: Label string (e.g., 'High', 'Medium')
        
        Returns:
            Value ID string or None if not found
        """
        field = field.lower()
        label_lower = label.lower().strip()
        
        if field in self.reverse_lookup:
            return self.reverse_lookup[field].get(label_lower)
        return None
    
    def get_all_values_for_field(self, field: str) -> Dict[str, str]:
        """
        Get all value->label mappings for a field
        
        Args:
            field: Field name
        
        Returns:
            Dictionary mapping values to labels
        """
        field = field.lower()
        return self.picklist_data.get(field, {}).copy()
    
    def normalize_value(self, field: str, input_value: str) -> Optional[str]:
        """
        Normalize a value or label to the standard value ID
        
        This function handles:
        - If input is already a value ID, return it
        - If input is a label, convert to value ID
        - Case-insensitive matching
        
        Args:
            field: Field name
            input_value: Either a value ID or label
        
        Returns:
            Normalized value ID or None if not found
        """
        field = field.lower()
        input_value = str(input_value).strip()
        
        # First check if it's already a valid value
        if field in self.picklist_data:
            if input_value in self.picklist_data[field]:
                return input_value
        
        # Try to find by label (case-insensitive)
        if field in self.reverse_lookup:
            label_lower = input_value.lower()
            if label_lower in self.reverse_lookup[field]:
                return self.reverse_lookup[field][label_lower]
        
        return None
    
    def normalize_label(self, field: str, input_value: str) -> Optional[str]:
        """
        Normalize a value or label to the standard label
        
        This function handles:
        - If input is a value ID, convert to label
        - If input is already a label, return it (normalized)
        - Case-insensitive matching
        
        Args:
            field: Field name
            input_value: Either a value ID or label
        
        Returns:
            Normalized label or None if not found
        """
        field = field.lower()
        input_value = str(input_value).strip()
        
        # First check if it's a value ID
        if field in self.picklist_data:
            if input_value in self.picklist_data[field]:
                return self.picklist_data[field][input_value]
        
        # Try to find by label (case-insensitive) and return the canonical label
        if field in self.reverse_lookup:
            label_lower = input_value.lower()
            if label_lower in self.reverse_lookup[field]:
                value = self.reverse_lookup[field][label_lower]
                # Return the canonical label from value->label mapping
                return self.picklist_data[field].get(value)
        
        return None
    
    def is_valid_value(self, field: str, value: str) -> bool:
        """Check if a value ID is valid for a field"""
        field = field.lower()
        if field in self.picklist_data:
            return str(value) in self.picklist_data[field]
        return False
    
    def is_valid_label(self, field: str, label: str) -> bool:
        """Check if a label is valid for a field"""
        field = field.lower()
        label_lower = label.lower().strip()
        if field in self.reverse_lookup:
            return label_lower in self.reverse_lookup[field]
        return False
    
    def get_fields(self) -> List[str]:
        """Get list of all available fields"""
        return list(self.picklist_data.keys())
    
    def format_for_prompt(self, field: str) -> str:
        """
        Format picklist options for LLM prompt
        
        Args:
            field: Field name
        
        Returns:
            Formatted string with value: label pairs
        """
        field = field.lower()
        if field not in self.picklist_data:
            return f"{field.upper()}: No options available"
        
        options = []
        for value, label in sorted(self.picklist_data[field].items(), key=lambda x: int(x[0]) if x[0].lstrip('-').isdigit() else 0):
            options.append(f'"{value}": "{label}"')
        
        return f"{field.upper()}: {{{', '.join(options)}}}"


# Global instance (lazy loaded)
_picklist_loader: Optional[PicklistLoader] = None


def get_picklist_loader(csv_path: str = None) -> PicklistLoader:
    """
    Get or create global picklist loader instance
    
    Args:
        csv_path: Optional path to CSV file (only used on first call)
    
    Returns:
        PicklistLoader instance
    """
    global _picklist_loader
    if _picklist_loader is None:
        _picklist_loader = PicklistLoader(csv_path)
    return _picklist_loader

