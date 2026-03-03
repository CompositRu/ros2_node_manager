# Monitoring Agent WebSocket Protocol

JSON-RPC 2.0 over WebSocket between `monitoring_agent` (server inside Docker) and `AgentConnection` (client outside Docker).

## Transport

- **Server**: `ws://0.0.0.0:{port}` inside Docker container (default port: 9090)
- **Client**: connects to `ws://{host}:{port}` or via Docker port mapping
- **Encoding**: UTF-8 JSON
- **Max message size**: 1 MB

## Message Format

### Request (client → server)
```json
{
  "jsonrpc": "2.0",
  "method": "graph.nodes",
  "params": {},
  "id": 1
}
```

### Response (server → client)
```json
{
  "jsonrpc": "2.0",
  "result": [...],
  "id": 1
}
```

### Error Response
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32000,
    "message": "Node not found",
    "data": {"node": "/missing_node"}
  },
  "id": 1
}
```

### Subscription Event (server → client, no id)
```json
{
  "jsonrpc": "2.0",
  "method": "event",
  "params": {
    "subscription": "sub_abc123",
    "channel": "topic.echo",
    "data": {...}
  }
}
```

## Error Codes

| Code | Meaning |
|------|---------|
| -32700 | Parse error |
| -32600 | Invalid request |
| -32601 | Method not found |
| -32602 | Invalid params |
| -32603 | Internal error |
| -32000 | Node not found |
| -32001 | Topic not found |
| -32002 | Service call failed |
| -32003 | Timeout |
| -32004 | Subscription error |

---

## Commands: Graph Introspection

### `graph.nodes`
List all running nodes (filtered from technical nodes).

**Params**: `{}` (none)

**Result**:
```json
["/node1", "/namespace/node2", "/namespace/node3"]
```

### `graph.node_info`
Get node publishers, subscribers, services, actions.

**Params**:
```json
{"node": "/namespace/node_name"}
```

**Result**:
```json
{
  "subscribers": ["/topic1", "/topic2"],
  "publishers": ["/topic3"],
  "services": ["/node/get_state", "/node/describe_parameters"],
  "actions": []
}
```

### `graph.topics`
List all topics with message types.

**Params**: `{}`

**Result**:
```json
[
  {"name": "/rosout", "type": "rcl_interfaces/msg/Log"},
  {"name": "/diagnostics", "type": "diagnostic_msgs/msg/DiagnosticArray"}
]
```

### `graph.topic_info`
Get detailed topic info (publishers, subscribers).

**Params**:
```json
{"topic": "/topic_name"}
```

**Result**:
```json
{
  "type": "geometry_msgs/msg/Twist",
  "publishers": ["/teleop_turtle"],
  "subscribers": ["/turtlesim"]
}
```

### `graph.services`
List all services.

**Params**: `{}`

**Result**:
```json
["/node/get_state", "/node/describe_parameters"]
```

### `graph.services_typed`
List all services with interface types.

**Params**: `{}`

**Result**:
```json
[
  {"name": "/node/get_state", "type": "lifecycle_msgs/srv/GetState"},
  {"name": "/node/describe_parameters", "type": "rcl_interfaces/srv/DescribeParameters"}
]
```

### `graph.interface_show`
Get interface definition text.

**Params**:
```json
{"type": "geometry_msgs/msg/Twist"}
```

**Result**:
```json
{"definition": "Vector3 linear\n  float64 x\n  ..."}
```

---

## Commands: Lifecycle

### `lifecycle.get_state`
Get lifecycle state of a node.

**Params**:
```json
{"node": "/lifecycle_node"}
```

**Result**:
```json
{"state": "active", "id": 3}
```

### `lifecycle.set_state`
Execute lifecycle transition.

**Params**:
```json
{"node": "/lifecycle_node", "transition": "activate"}
```

**Result**:
```json
{"success": true, "message": "Transition 'activate' successful"}
```

### `lifecycle.is_lifecycle`
Check if a node is a lifecycle node.

**Params**:
```json
{"node": "/some_node"}
```

**Result**:
```json
{"is_lifecycle": true}
```

---

## Commands: Parameters

### `params.dump`
Get all parameters of a node.

**Params**:
```json
{"node": "/node_name"}
```

**Result**:
```json
{
  "use_sim_time": false,
  "robot_description": "...",
  "update_rate": 30.0
}
```

### `params.set`
Set parameters on a node.

**Params**:
```json
{
  "node": "/node_name",
  "parameters": {"update_rate": 60.0, "debug": true}
}
```

**Result**:
```json
{"success": true, "results": [{"name": "update_rate", "success": true}]}
```

---

## Commands: Service Call

### `service.call`
Call a ROS2 service.

**Params**:
```json
{
  "service": "/node/set_parameters",
  "type": "rcl_interfaces/srv/SetParameters",
  "request": {"parameters": [{"name": "x", "value": {"type": 3, "double_value": 1.0}}]}
}
```

**Result**:
```json
{"response": "..."}
```

---

## Commands: Process Management

### `process.kill`
Kill a process by pattern.

**Params**:
```json
{"pattern": "node_name_pattern"}
```

**Result**:
```json
{"success": true, "pid": 12345}
```

---

## Subscriptions

### `subscribe`
Subscribe to a data stream.

**Params**:
```json
{
  "channel": "topic.echo",
  "params": {"topic": "/rosout", "no_arr": true, "max_size": 10240}
}
```

**Result**:
```json
{"subscription": "sub_abc123"}
```

After subscribing, server sends `event` messages (see format above).

### `unsubscribe`
Stop a subscription.

**Params**:
```json
{"subscription": "sub_abc123"}
```

**Result**:
```json
{"success": true}
```

### Available Channels

#### `topic.echo`
Stream messages from a topic.

**Subscribe params**:
```json
{"topic": "/topic_name", "no_arr": true, "max_size": 10240}
```

**Event data**:
```json
{"topic": "/topic_name", "data": {...message fields...}, "timestamp": 1234567890.123}
```

#### `topic.hz`
Stream publish rate for a topic.

**Subscribe params**:
```json
{"topic": "/topic_name", "window_size": 100}
```

**Event data** (sent every 2s):
```json
{"topic": "/topic_name", "hz": 30.05, "min_delta": 0.030, "max_delta": 0.036, "std_dev": 0.001}
```

#### `logs`
Stream /rosout messages.

**Subscribe params**:
```json
{"node_filter": "/specific_node", "min_level": 20, "with_history": true, "history_count": 100}
```

**Event data**:
```json
{
  "timestamp": 1234567890.123,
  "level": 20,
  "level_name": "INFO",
  "node": "/node_name",
  "message": "Log message text"
}
```

#### `diagnostics`
Stream /diagnostics messages.

**Subscribe params**: `{}`

**Event data**:
```json
{
  "source": "diagnostics",
  "statuses": [
    {"name": "CPU Usage", "level": 0, "message": "OK", "values": [...]}
  ]
}
```

---

## Heartbeat

Server sends ping every 10s. Client must respond with pong (WebSocket protocol level).
If no pong received within 30s, server closes connection.

Client can send:
```json
{"jsonrpc": "2.0", "method": "ping", "id": 99}
```

Server responds:
```json
{"jsonrpc": "2.0", "result": {"uptime": 3600, "subscriptions": 3, "clients": 1}, "id": 99}
```
