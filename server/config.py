"""Configuration loader for Tram Monitoring System."""

from pathlib import Path
from typing import Optional

import yaml
from pydantic_settings import BaseSettings

from .models import ServerConfig, AlertConfig, TopicGroupsConfig


class Settings(BaseSettings):
    """Application settings."""
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    
    # Paths
    config_dir: Path = Path(__file__).parent.parent / "config"
    data_dir: Path = Path(__file__).parent.parent / "data"
    
    # Polling
    node_poll_interval: float = 5.0  # seconds
    type_check_delay: float = 0.5    # delay before checking node type
    
    # Limits
    max_log_buffer: int = 1000  # max log messages per node
    
    class Config:
        env_prefix = "ROS2_NODE_MANAGER_"


settings = Settings()


def load_servers_config() -> list[ServerConfig]:
    """Load servers configuration from YAML file."""
    config_file = settings.config_dir / "config.yaml"

    if not config_file.exists():
        return [
            ServerConfig(
                id="local-agent",
                name="Local Agent",
            )
        ]

    with open(config_file) as f:
        data = yaml.safe_load(f)

    servers = []
    for srv in data.get("servers", []):
        servers.append(ServerConfig(**srv))

    return servers


def get_server_by_id(server_id: str) -> Optional[ServerConfig]:
    """Get server config by ID."""
    servers = load_servers_config()
    for srv in servers:
        if srv.id == server_id:
            return srv
    return None


def load_alert_config() -> AlertConfig:
    """Load alert configuration from YAML file."""
    # Сначала пробуем отдельный файл alerts.yaml
    alerts_file = settings.config_dir / "alerts.yaml"
    if alerts_file.exists():
        with open(alerts_file) as f:
            data = yaml.safe_load(f)
            if data:
                return AlertConfig(**data)
    
    return AlertConfig()


def load_topic_groups_config() -> TopicGroupsConfig:
    """Load topic groups configuration from YAML file."""
    config_file = settings.config_dir / "topic_groups.yaml"
    if config_file.exists():
        with open(config_file) as f:
            data = yaml.safe_load(f)
            if data:
                return TopicGroupsConfig(**data)

    return TopicGroupsConfig()