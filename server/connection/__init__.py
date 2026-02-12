"""Connection module."""

from .base import BaseConnection, ConnectionError, ContainerNotFoundError
from .local import LocalDockerConnection
from .ssh import SSHDockerConnection

__all__ = [
    "BaseConnection",
    "ConnectionError",
    "ContainerNotFoundError",
    "LocalDockerConnection",
    "SSHDockerConnection"
]
