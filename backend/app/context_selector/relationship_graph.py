from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

import yaml


class RelationshipGraph:
    def __init__(self, metadata_path: Path) -> None:
        self.metadata_path = metadata_path
        self.index = self.load_relationship_index()

    def load_relationship_index(self) -> list[dict[str, Any]]:
        path = self.metadata_path / "context" / "relationship_index.yml"
        if not path.exists():
            return []
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        relationships = payload.get("relationships", [])
        if not isinstance(relationships, list):
            return []
        return [r for r in relationships if isinstance(r, dict)]

    def find_join_path(self, source_tables: list[str], target_tables: list[str], max_hops: int = 3) -> list[dict[str, Any]]:
        approved = [r for r in self.index if bool(r.get("approved", False))]
        if not approved:
            return []

        adjacency: dict[str, list[dict[str, Any]]] = {}
        for rel in approved:
            frm = str(rel.get("from_table", "")).upper()
            to = str(rel.get("to_table", "")).upper()
            if not frm or not to:
                continue
            adjacency.setdefault(frm, []).append(rel)
            reverse = {
                **rel,
                "from_table": to,
                "from_column": rel.get("to_column", ""),
                "to_table": frm,
                "to_column": rel.get("from_column", ""),
            }
            adjacency.setdefault(to, []).append(reverse)

        src = {s.upper() for s in source_tables}
        tgt = {t.upper() for t in target_tables}
        if not src or not tgt:
            return []

        queue: deque[tuple[str, list[dict[str, Any]], set[str]]] = deque()
        for s in src:
            queue.append((s, [], {s}))

        while queue:
            node, path, visited = queue.popleft()
            if node in tgt and path:
                return path
            if len(path) >= max_hops:
                continue
            for edge in adjacency.get(node, []):
                nxt = str(edge.get("to_table", "")).upper()
                if not nxt or nxt in visited:
                    continue
                queue.append((nxt, path + [edge], visited | {nxt}))
        return []

    def expand_tables_with_join_path(self, selected_tables: list[str], question: str, max_hops: int = 3) -> tuple[list[str], list[list[str]], list[dict[str, Any]]]:
        selected = [s.upper() for s in selected_tables]
        if not selected:
            return [], [], []

        all_nodes = {
            str(r.get("from_table", "")).upper()
            for r in self.index
            if bool(r.get("approved", False))
        } | {
            str(r.get("to_table", "")).upper()
            for r in self.index
            if bool(r.get("approved", False))
        }

        targets = set(selected)
        q = question.lower()
        if any(token in q for token in ("municipio", "municipios", "ciudad", "localidad")) and "SAC.MUNICIPIOS" in all_nodes:
            targets.add("SAC.MUNICIPIOS")

        merged = list(dict.fromkeys(selected))
        table_paths: list[list[str]] = []
        join_edges: list[dict[str, Any]] = []

        for src in list(merged):
            for tgt in list(targets):
                if src == tgt:
                    continue
                path_edges = self.find_join_path([src], [tgt], max_hops=max_hops)
                if not path_edges:
                    continue
                nodes = [src]
                for edge in path_edges:
                    next_table = str(edge.get("to_table", "")).upper()
                    if next_table:
                        nodes.append(next_table)
                        if next_table not in merged:
                            merged.append(next_table)
                if len(nodes) > 1:
                    table_paths.append(nodes)
                for edge in path_edges:
                    key = (
                        str(edge.get("from_table", "")).upper(),
                        str(edge.get("from_column", "")).upper(),
                        str(edge.get("to_table", "")).upper(),
                        str(edge.get("to_column", "")).upper(),
                    )
                    if key[0] and key[2]:
                        if key not in {
                            (
                                str(e.get("from_table", "")).upper(),
                                str(e.get("from_column", "")).upper(),
                                str(e.get("to_table", "")).upper(),
                                str(e.get("to_column", "")).upper(),
                            )
                            for e in join_edges
                        }:
                            join_edges.append(edge)

        return merged, table_paths, join_edges
