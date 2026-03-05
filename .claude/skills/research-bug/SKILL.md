---
name: research-bug
description: Investigate a bug in an isolated context
context: fork
agent: root-cause
disable-model-invocation: true
---

Investigate bug: $ARGUMENTS

Process:
1. Find the smallest relevant set of files
2. Read logs only as needed
3. Return:
   - root cause hypothesis
   - strongest supporting evidence
   - missing information
   - next best check
