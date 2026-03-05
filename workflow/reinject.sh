#!/bin/bash
# Re-inject workflow state after /compact
# Выводит краткую сводку текущего состояния проекта в stdout.
# Claude Code подхватит это как контекст после compaction.

WORKFLOW_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== WORKFLOW STATE (re-injected after compaction) ==="
echo ""

# Current plan phase
if [ -f "$WORKFLOW_DIR/PLAN.md" ]; then
    echo "--- PLAN (текущая фаза) ---"
    sed -n '/^## Текущая фаза/,/^## /{ /^## Будущие/d; p; }' "$WORKFLOW_DIR/PLAN.md"
    echo ""
fi

# Active TODOs
if [ -f "$WORKFLOW_DIR/TODO.md" ]; then
    echo "--- TODO (активные задачи) ---"
    sed -n '/^## В работе/,/^## /{p;}' "$WORKFLOW_DIR/TODO.md" | head -20
    echo ""
    # Show blockers if any
    BLOCKERS=$(sed -n '/^## Блокеры/,/^## /{/^_Нет/!{/^## /!p;}}' "$WORKFLOW_DIR/TODO.md" | grep -v '^$' | grep -v '^## ')
    if [ -n "$BLOCKERS" ]; then
        echo "--- BLOCKERS ---"
        echo "$BLOCKERS"
        echo ""
    fi
fi

# Key decisions (just headers)
if [ -f "$WORKFLOW_DIR/DECISIONS.md" ]; then
    echo "--- DECISIONS (ключевые решения) ---"
    grep '^### D[0-9]' "$WORKFLOW_DIR/DECISIONS.md"
    echo ""
fi

echo "Подробнее: workflow/PLAN.md, workflow/TODO.md, workflow/DECISIONS.md, workflow/EVIDENCE.md"
echo "Архитектура: workflow/ARCHITECTURE.md"
echo "=== END WORKFLOW STATE ==="
