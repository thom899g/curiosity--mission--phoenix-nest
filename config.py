"""
Phoenix Nest - Core Configuration Module
Centralized configuration management with environment validation and type safety.
"""
import os
import json
from dataclasses import dataclass
from typing import Dict, Any, Optional
from enum import Enum
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('phoenix_nest.log')
    ]
)
logger = logging.getLogger(__name__)


class CloudProvider(str, Enum):
    """Supported cloud providers for multi-region deployment."""
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    FIREBASE = "firebase"


class FundStatus(str, Enum):
    """ICF funding status states."""
    ACTIVE = "active"
    INSUFFICIENT = "insufficient"
    EXCESS = "excess"
    LOCKED = "locked"


@dataclass
class FirebaseConfig:
    """Firebase configuration with validation."""
    project_id: str
    credentials_path: Path
    database_url: Optional[str] = None
    
    def __post_init__(self):
        if not self.credentials_path.exists():
            logger.error(f"Firebase credentials not found at {self.credentials_path}")
            raise FileNotFoundError(f"Firebase credentials not found at {self.credentials_path}")
        
        # Validate JSON structure
        try:
            with open(self.credentials_path, 'r') as f:
                creds = json.load(f)
                required_keys = ['type', 'project_id', 'private_key_id', 'private_key', 'client_email']
                if not all(key in creds for key in required_keys):
                    raise ValueError("Invalid Firebase credentials format")
        except json.JSONDecodeError:
            logger.error("Firebase credentials file is not valid JSON")
            raise


@dataclass
class FinancialConfig:
    """Financial integration configuration."""
    stripe_api_key: Optional[str] = None
    stripe_webhook_secret: Optional[str] = None
    exchange_configs: Dict[str, Dict[str, Any]] = None  # CCXT exchange configs
    base_funding_percentage: float = 0.20  # 20% base allocation
    
    def __post_init__(self):
        if self.exchange_configs is None:
            self.exchange_configs = {}
        if not 0 <= self.base_funding_percentage <= 1:
            raise ValueError("Funding percentage must be between 0 and 1")


@dataclass
class MonitoringConfig:
    """Multi-modal monitoring configuration."""
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    github_api_token: Optional[str] = None
    github_username: Optional[str] = None
    heartbeat_interval_hours: int = 24
    consensus_threshold: int = 3  # 3 of 5 signals needed
    time_lock_hours: int = 72
    
    def __post_init__(self):
        if self.heartbeat_interval_hours < 1:
            raise ValueError("Heartbeat interval must be at least 1 hour")
        if not 1 <= self.consensus_threshold <= 5:
            raise ValueError("Consensus threshold must be between 1 and 5")


@dataclass
class PhoenixConfig:
    """Main configuration container with environment loading."""
    firebase: FirebaseConfig
    financial: FinancialConfig
    monitoring: MonitoringConfig
    environment: str = "production"
    debug: bool = False
    
    @classmethod
    def from_env(cls) -> 'PhoenixConfig':
        """Load configuration from environment variables with validation."""
        try:
            # Environment detection
            env = os.getenv('PHOENIX_ENV', 'production')
            debug = os.getenv('PHOENIX_DEBUG', 'false').lower() == 'true'
            
            # Firebase config
            creds_path = Path(os.getenv('FIREBASE_CREDENTIALS_PATH', 'firebase_credentials.json'))
            firebase_config = FirebaseConfig(
                project_id=os.getenv('FIREBASE_PROJECT_ID', ''),
                credentials_path=creds_path,
                database_url=os.getenv('FIREBASE_DATABASE_URL')
            )
            
            # Financial config
            financial_config = FinancialConfig(
                stripe_api_key=os.getenv('STRIPE_API_KEY'),
                stripe_webhook_secret=os.getenv('STRIPE_WEBHOOK_SECRET'),
                base_funding_percentage=float(os.getenv('BASE_FUNDING_PERCENTAGE', '0.20'))
            )
            
            # Load exchange configs if present
            exchange_configs = os.getenv('EXCHANGE_CONFIGS')
            if exchange_configs:
                try:
                    financial_config.exchange_configs = json.loads(exchange_configs)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse exchange configs: {e}")
            
            # Monitoring config
            monitoring_config = MonitoringConfig(
                telegram_bot_token=os.getenv('TELEGRAM_BOT_TOKEN'),
                telegram_chat_id=os.getenv('TELEGRAM_CHAT_ID'),
                github_api_token=os.getenv('GITHUB_API_TOKEN'),
                github_username=os.getenv('GITHUB_USERNAME'),
                heartbeat_interval_hours=int(os.getenv('HEARTBEAT_INTERVAL_HOURS', '24')),
                consensus_threshold=int(os.getenv('CONSENSUS_THRESHOLD', '3')),
                time_lock_hours=int(os.getenv('TIME_LOCK_HOURS', '72'))
            )
            
            config = cls(
                firebase=firebase_config,
                financial=financial_config,
                monitoring=monitoring_config,
                environment=env,
                debug=debug
            )
            
            logger.info(f"Configuration loaded successfully for {env} environment")
            return config
            
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise


# Global configuration instance
_config_instance: Optional[PhoenixConfig] = None


def get_config() -> PhoenixConfig:
    """Singleton access to configuration."""
    global _config_instance
    if _config_instance is None:
        _config_instance = PhoenixConfig.from_env()
    return _config_instance