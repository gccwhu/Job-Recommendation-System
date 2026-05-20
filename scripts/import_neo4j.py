from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kg.config import Settings
from kg.graph import load_graph_from_file
from kg.repository import Neo4jGraphRepository


def main() -> None:
    settings = Settings.from_env()
    graph = load_graph_from_file(settings.data_file)
    repository = Neo4jGraphRepository(settings, allow_empty=True)
    try:
        repository.sync_graph(graph)
        stats = repository.stats()
        print("Neo4j graph import finished")
        print(stats.model_dump_json(indent=2))
    finally:
        repository.close()


if __name__ == "__main__":
    main()
