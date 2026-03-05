---
name: review
description: Code review recent changes in an isolated context
context: fork
agent: code-review
disable-model-invocation: true
user_invocable: true
---

Review code changes: $ARGUMENTS

Default: review `git diff` (unstaged changes).
If no arguments, review all uncommitted changes.
