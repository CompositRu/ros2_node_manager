---
name: check-agent-logs
description: Analyze monitoring_agent logs in an isolated context
context: fork
agent: analyze-agent-logs
disable-model-invocation: true
user_invocable: true
---

Analyze monitoring_agent logs: $ARGUMENTS

Find WebSocket errors, ROS2 API issues, subscription problems.
Return only actionable findings.
