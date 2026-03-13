"""
Firebase Firestore State Manager
Centralized state management with type-safe schemas, error handling, and automatic retries.
"""
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, TypeVar, Generic
from dataclasses import dataclass, asdict, field
import json
import logging

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore import Client as FirestoreClient
from google.cloud.firestore_v1 import DocumentSnapshot, Transaction
from google.cloud.firestore_v1.field_path import FieldPath
from google.api_core.exceptions import GoogleAPICallError, RetryError

from config import get_config, FundStatus

logger = logging.getLogger(__name__)
T = TypeVar('T')


@dataclass
class ICFState:
    """Immortal Continuity Fund state schema."""
    current_balance: float = 0.0
    target_balance: float = 500000.00
    last_profit_allocation: Optional[datetime] = None
    estimated_restoration_cost: float = 75000.00
    funding_rate_adjustment: float = 0.0  # Percentage adjustment from base
    status: FundStatus = FundStatus.ACTIVE
    performance_history: List[Dict[str, Any]] = field(default_factory=list)
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to Firestore-compatible dictionary."""
        data = asdict(self)
        # Convert datetime to ISO format string
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
            elif isinstance(value, FundStatus):
                data[key] = value.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ICFState':
        """Create ICFState from Firestore dictionary."""
        if not data:
            return cls()
        
        # Convert string dates back to datetime
        if 'last_profit_allocation' in data and data['last_profit_allocation']:
            data['last_profit_allocation'] = datetime.fromisoformat(data['last_profit_allocation'])
        if 'last_updated' in data and data['last_updated']:
            data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        
        # Convert string to FundStatus enum
        if 'status' in data:
            data['status'] = FundStatus(data['status'])
        
        return cls(**data)


@dataclass
class TriggerState:
    """Consensus-of-Silences trigger state schema."""
    heartbeat_last: Optional[datetime] = None
    github_last_commit: Optional[datetime] = None
    financial_last_tx: Optional[datetime] = None
    executive_token_last: Optional[datetime] = None
    panic_button_states: Dict[str, bool] = field(default_factory=lambda: {
        'trustee_1': False,
        'trustee_2': False,
        'trustee_3': False,
        'trustee_4': False,
        'trustee_5': False
    })
    consensus_reached: bool = False
    activation_time_lock: Optional[datetime] = None
    negative_signals: List[str] = field(default_factory=list)
    verification_nodes: Dict[str, bool] = field(default_factory=dict)
    last_checked: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to Firestore-compatible dictionary."""
        data = asdict(self)
        # Convert datetime to ISO format string
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TriggerState':
        """Create TriggerState from Firestore dictionary."""
        if not data:
            return cls()
        
        # Convert string dates back to datetime
        date_fields = ['heartbeat_last', 'github_last_commit', 'financial_last_tx',
                      'executive_token_last', 'activation_time_lock', 'last_checked']
        for field in date_fields:
            if field in data and data[field]:
                data[field] = datetime.fromisoformat(data[field])
        
        return cls(**data)


class FirebaseManager:
    """Firebase Firestore manager with automatic initialization and error handling."""
    
    _instance: Optional['FirebaseManager'] = None
    _client: Optional[FirestoreClient] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.config = get_config()
            self._initialize_firebase()
            self._initialized = True
    
    def _initialize_firebase(self) -> None:
        """Initialize Firebase Admin SDK with error handling."""
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(str(self.config.firebase.credentials_path))
                firebase_admin.initialize_app(cred, {
                    'projectId': self.config.firebase.project_id,
                    'databaseURL': self.config.firebase.database_url
                })
                logger.info("Firebase Admin SDK initialized successfully")
            
            self._client = firestore.client()
            logger.info(f"Firestore client connected to project: {self.config.firebase.project_id}")
            
            # Initialize collections if they don't exist
            self._initialize_collections()
            
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {e}")
            raise
    
    def _initialize_collections(self) -> None:
        """Ensure required collections and documents exist."""
        try:
            # Check/initialize ICF state
            icf_ref = self._client.collection('phoenix_nest').document('icf_state')
            if not icf_ref.get().exists:
                initial_state = ICFState()
                icf_ref.set(initial_state.to_dict())
                logger.info("Initialized ICF state document")
            
            # Check/initialize trigger state
            trigger_ref = self._client.collection('phoenix_nest').document('trigger_state')
            if not trigger_ref.get().exists:
                initial_trigger = TriggerState()
                trigger_ref.set(initial_trigger.to_dict())
                logger.info("Initialized trigger state document")
            
            # Create indexes collection
            indexes_ref = self._client.collection('phoenix_nest').document('indexes')
            if not indexes_ref.get().exists:
                indexes_ref.set({
                    'last_updated': datetime.now(timezone.utc).isoformat(),
                    'collections': ['icf_state', 'trigger_state', 'drills', 'transactions']
                })
                
        except Exception as e:
            logger.error(f"Failed to initialize collections: {e}")
            raise
    
    @property
    def client(self) -> FirestoreClient:
        """Get Firestore client with lazy initialization."""
        if self._client is None:
            self._initialize_firebase()
        return self._client
    
    def get_icf_state(self) -> ICFState:
        """Retrieve current ICF state with error handling."""
        try:
            doc_ref = self.client.collection('phoenix_nest').document('icf_state')
            snapshot = doc_ref.get()
            
            if not snapshot.exists:
                logger.warning("ICF state document not found, creating default")
                default_state = ICFState()
                doc_ref.set(default_state.to_dict())
                return default_state
            
            data = snapshot.to_dict()
            return ICFState.from_dict(data)
            
        except GoogleAPICallError as e:
            logger.error(f"Firestore API error while getting ICF state: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting ICF state: {e}")
            raise
    
    def update_icf_state(self, updates: Dict[str, Any], transaction: Optional[Transaction] = None) -> bool:
        """Update ICF state with atomic operations."""
        try:
            doc_ref = self.client.collection('phoenix_nest').document('icf_state')
            
            # Add timestamp
            updates['last_updated'] = datetime.now(timezone.utc).iso