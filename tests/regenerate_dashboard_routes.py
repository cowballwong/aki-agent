"""Rewrite the dashboard route snapshot.

Run when a route is genuinely added or removed:

    python tests/regenerate_dashboard_routes.py

The diff it produces belongs in the change under review. That is the point --
a route appearing should be a visible decision, not something that arrives
alongside an unrelated edit.
"""

from __future__ import annotations

import json
from pathlib import Path

from aki_agent.dashboard import create_app

HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE / "fixtures" / "dashboard_routes.json"
CONFIG = HERE.parent / "configs" / "examples" / "architecture.yaml"


def main() -> int:
    app = create_app(CONFIG)
    rules = []
    for rule in app.url_map.iter_rules():
        methods = sorted(m for m in rule.methods
                         if m not in ("HEAD", "OPTIONS"))
        rules.append({"rule": str(rule.rule),
                      "endpoint": rule.endpoint,
                      "methods": methods})
    rules.sort(key=lambda one: (one["rule"], one["endpoint"]))
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(rules, indent=1, sort_keys=True),
                        encoding="utf-8")
    print(f"{len(rules)} routes written to {SNAPSHOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
