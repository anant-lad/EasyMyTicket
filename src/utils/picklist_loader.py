"""
Picklist Loader Utility
Loads and manages picklist values from CSV for data normalization
"""
import csv
import logging
import os
from typing import Dict, Optional, List, Tuple
from pathlib import Path

log = logging.getLogger(__name__)


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
            # Try clean name first, fall back to original name with space
            csv_path = project_root / "dataset" / "picklist_values.csv"
            if not csv_path.exists():
                csv_path = project_root / "dataset" / "picklist_values (1).csv"
        
        self.csv_path = csv_path
        self.picklist_data: Dict[str, Dict[str, str]] = {}  # {field: {value: label}}
        self.reverse_lookup: Dict[str, Dict[str, str]] = {}  # {field: {label: value}}
        self._load_picklist()
    
    # Built-in defaults — mirrors picklist_values.csv which is excluded from Docker image.
    # Update here whenever the CSV changes.
    _DEFAULTS: Dict[str, Dict[str, str]] = {
        "issuetype": {
            "4":  "Hardware & Equipment",
            "5":  "Software & Applications",
            "6":  "Network & Connectivity",
            "7":  "Site Survey & Assessment",
            "8":  "Server & Database",
            "9":  "Active Directory & Access",
            "10": "General IT Support",
            "11": "Cloud & Office 365",
            "12": "Mobile Devices",
            "13": "Backup & Disaster Recovery",
            "14": "Cybersecurity",
            "15": "Email & Password",
            "16": "VoIP & Phone",
            "17": "End User Support",
            "18": "Printing & Peripherals",
            "19": "Project & Consulting",
            "20": "Compliance & Audit",
            "21": "Virtualization",
            "22": "Wireless & WiFi",
            "23": "Remote Access & VPN",
            "24": "Licensing",
            "25": "Training & Documentation",
            "26": "Other",
        },
        "subissuetype": {
            "1":  "Laptop/Desktop",
            "2":  "Printer/Scanner",
            "3":  "Monitor/Display",
            "4":  "Keyboard/Mouse/Peripherals",
            "5":  "Mobile Device",
            "6":  "Operating System",
            "7":  "Application/Software",
            "8":  "Driver/Firmware",
            "9":  "Internet/WAN",
            "10": "LAN/Switch",
            "11": "WiFi",
            "12": "VPN/Remote Access",
            "13": "Email",
            "14": "Password Reset",
            "15": "Account Lockout",
            "16": "Permissions/Access",
            "17": "Camera/Webcam",
            "18": "Audio/Speaker/Microphone",
            "19": "Storage/Disk",
            "20": "Performance/Speed",
            "21": "Crash/BSOD",
            "22": "Security/Virus",
            "23": "Backup/Restore",
            "24": "Hardware Replacement",
            "25": "Other",
        },
        "ticketcategory": {
            "2":   "Service Request",
            "3":   "Incident",
            "4":   "Problem",
            "101": "Maintenance",
            "102": "Change Request",
            "103": "Project",
            "107": "Monitoring Alert",
            "108": "Security Event",
            "109": "Compliance",
        },
        "tickettype": {
            "1": "Break/Fix",
            "2": "New Request",
            "3": "How-To",
            "4": "Maintenance",
            "5": "Proactive",
        },
        "priority": {
            "1": "Critical",
            "2": "High",
            "3": "Medium",
            "4": "Low",
            "5": "Planning",
        },
        "status": {
            "1":  "Open",
            "5":  "Closed",
            "7":  "In Progress",
            "8":  "Pending",
            "15": "Resolved",
            "16": "Awaiting User",
            "17": "On Hold",
            "19": "Escalated",
            "28": "Cancelled",
        },
    }

    def _load_picklist(self):
        """Load picklist data from CSV file, falling back to built-in defaults."""
        if not os.path.exists(self.csv_path):
            import logging
            logging.getLogger(__name__).warning(
                "Picklist CSV not found at %s — using built-in defaults", self.csv_path
            )
            for field, values in self._DEFAULTS.items():
                self.picklist_data[field] = dict(values)
                self.reverse_lookup[field] = {v.lower(): k for k, v in values.items()}
            return
        
        log.info("PICKLIST:LOADING path=%s", self.csv_path)

        with open(self.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                field = row.get('Field', '').strip().lower()
                value = row.get('Value', '').strip()
                label = row.get('Label', '').strip()

                if not field or not value or not label:
                    continue

                if field not in self.picklist_data:
                    self.picklist_data[field] = {}
                    self.reverse_lookup[field] = {}

                self.picklist_data[field][value] = label

                label_lower = label.lower()
                if label_lower not in self.reverse_lookup[field]:
                    self.reverse_lookup[field][label_lower] = value

        total_fields = len(self.picklist_data)
        total_values = sum(len(values) for values in self.picklist_data.values())
        log.info("PICKLIST:LOADED fields=%d values=%d", total_fields, total_values)
    
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
        """Format picklist options for LLM prompt — returns label-only list so the
        model knows to reply with the exact label text (not the numeric code)."""
        field = field.lower()
        if field not in self.picklist_data:
            return f"{field.upper()}: No options available"

        labels = [
            label
            for _value, label in sorted(
                self.picklist_data[field].items(),
                key=lambda x: int(x[0]) if x[0].lstrip("-").isdigit() else 0,
            )
        ]
        return f"{field.upper()}: {' | '.join(labels)}"


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

