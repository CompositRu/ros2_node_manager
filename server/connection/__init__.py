"""Connection module."""

from .base import BaseConnection, ConnectionError, ContainerNotFoundError
from .local import LocalDockerConnection
from .ssh import SSHDockerConnection
from .agent import AgentConnection

__all__ = [
    "BaseConnection",
    "ConnectionError",
    "ContainerNotFoundError",
    "LocalDockerConnection",
    "SSHDockerConnection",
    "AgentConnection",
]
