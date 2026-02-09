"""Configuration loader for ROS2 Node Manager."""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic_settings import BaseSettings

from .models import ServerConfig, ServerType, AlertConfig


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
    config_file = settings.config_dir / "servers.yaml"
    
    if not config_file.exists():
        # Return default local config if no file
        return [
            ServerConfig(
                id="local",
                name="Local Docker",
                type=ServerType.LOCAL,
                container="tram_autoware"
            )
        ]
    
    with open(config_file) as f:
        data = yaml.safe_load(f)
    
    servers = []
    for srv in data.get("servers", []):
        # Handle ssh_key path expansion
        if "ssh_key" in srv and srv["ssh_key"]:
            srv["ssh_key"] = os.path.expanduser(srv["ssh_key"])
        
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
    
    # Fallback: читаем из servers.yaml
    servers_file = settings.config_dir / "servers.yaml"
    if servers_file.exists():
        with open(servers_file) as f:
            data = yaml.safe_load(f)
            alerts_data = data.get("alerts", {})
            if alerts_data:
                return AlertConfig(**alerts_data)
    
    # Default config
    return AlertConfig()