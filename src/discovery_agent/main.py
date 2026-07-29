"""Entry point: run the discovery scout over venues that need one."""

from __future__ import annotations

from . import graph
from .config import settings


def main() -> None:
    print(f"[discovery-agent] model={settings.scout_model} max_venues={settings.scout_max_venues}")
    count = graph.run()
    print(f"[discovery-agent] scouted {count} venue(s).")


if __name__ == "__main__":
    main()
