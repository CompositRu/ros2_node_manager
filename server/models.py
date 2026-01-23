"""Pydantic models for ROS2 Node Manager."""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class NodeType(str, Enum):
    """Тип ноды."""
    UNKNOWN = "unknown"
    LIFECYCLE = "lifecycle"
    REGULAR = "regular"


class NodeStatus(str, Enum):
    """Статус ноды."""
    ACTIVE = "active"
    INACTIVE = "inactive"


class LifecycleState(str, Enum):
    """Состояние lifecycle ноды."""
    UNKNOWN = "unknown"
    UNCONFIGURED = "unconfigured"
    INACTIVE = "inactive"
    ACTIVE = "active"
    FINALIZED = "finalized"


class ServerType(str, Enum):
    """Тип подключения к серверу."""
    LOCAL = "local"
    SSH = "ssh"


# === Server Models ===

class ServerConfig(BaseModel):
    """Конфигурация сервера."""
    id: str
    name: str
    type: ServerType
    container: str
    host: Optional[str] = None
    port: int = 22
    user: Optional[str] = None
    ssh_key: Optional[str] = None
    password: Optional[str] = None


class ServerStatus(BaseModel):
    """Статус подключения к серверу."""
    id: str
    name: str
    type: ServerType
    connected: bool = False
    error: Optional[str] = None


# === Node Models ===

class NodeInfo(BaseModel):
    """Полная информация о ноде."""
    name: str
    first_seen: datetime
    last_seen: datetime
    type: NodeType = NodeType.UNKNOWN
    status: NodeStatus = NodeStatus.ACTIVE
    lifecycle_state: Optional[LifecycleState] = None
    parameters: dict = Field(default_factory=dict)
    subscribers: list[str] = Field(default_factory=list)
    publishers: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)


class NodeState(BaseModel):
    """Состояние всех нод (для сохранения в файл)."""
    last_updated: datetime
    server_id: str
    nodes: dict[str, NodeInfo] = Field(default_factory=dict)


class NodeSummary(BaseModel):
    """Краткая информация о ноде для дерева."""
    name: str
    type: NodeType
    status: NodeStatus
    lifecycle_state: Optional[LifecycleState] = None


# === API Response Models ===

class NodesResponse(BaseModel):
    """Ответ со списком нод."""
    total: int
    active: int
    inactive: int
    nodes: list[NodeSummary]


class NodeDetailResponse(BaseModel):
    """Детальная информация о ноде."""
    node: NodeInfo


class ActionResponse(BaseModel):
    """Ответ на действие."""
    success: bool
    message: str


class LogMessage(BaseModel):
    """Сообщение лога."""
    timestamp: datetime
    level: str
    node_name: str
    message: str


# === WebSocket Models ===

class WSNodesUpdate(BaseModel):
    """WebSocket обновление статуса нод."""
    type: str = "nodes_update"
    total: int
    active: int
    inactive: int
    nodes: dict[str, NodeStatus]


class WSLogMessage(BaseModel):
    """WebSocket сообщение лога."""
    type: str = "log"
    timestamp: str
    level: str
    message: str
