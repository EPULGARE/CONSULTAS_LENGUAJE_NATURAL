from pathlib import Path
import shutil
import uuid

import yaml

from app.context_selector.relationship_graph import RelationshipGraph


def _mk_workspace_tmp() -> Path:
    base = Path("backend/tests/_tmp") / str(uuid.uuid4())
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cleanup(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _write_index(root: Path, relationships: list[dict]) -> None:
    path = root / "metadata" / "context"
    path.mkdir(parents=True, exist_ok=True)
    (path / "relationship_index.yml").write_text(
        yaml.safe_dump({"relationships": relationships}, sort_keys=False),
        encoding="utf-8",
    )


def test_find_join_path_medidores_to_municipios_via_clientes():
    root = _mk_workspace_tmp()
    try:
        _write_index(
            root,
            [
                {"from_table": "SAC.MEDIDORES", "from_column": "CLIENTE_ID", "to_table": "SAC.CLIENTES", "to_column": "CLIENTE_ID", "approved": True},
                {"from_table": "SAC.CLIENTES", "from_column": "MUNICIPIO", "to_table": "SAC.MUNICIPIOS", "to_column": "MUNICIPIO", "approved": True},
            ],
        )
        graph = RelationshipGraph(root / "metadata")
        path = graph.find_join_path(["SAC.MEDIDORES"], ["SAC.MUNICIPIOS"])
        assert len(path) == 2
        assert path[0]["to_table"] == "SAC.CLIENTES"
    finally:
        _cleanup(root)


def test_find_join_path_ignores_not_approved():
    root = _mk_workspace_tmp()
    try:
        _write_index(
            root,
            [
                {"from_table": "SAC.MEDIDORES", "from_column": "CLIENTE_ID", "to_table": "SAC.CLIENTES", "to_column": "CLIENTE_ID", "approved": False},
                {"from_table": "SAC.CLIENTES", "from_column": "MUNICIPIO", "to_table": "SAC.MUNICIPIOS", "to_column": "MUNICIPIO", "approved": True},
            ],
        )
        graph = RelationshipGraph(root / "metadata")
        path = graph.find_join_path(["SAC.MEDIDORES"], ["SAC.MUNICIPIOS"])
        assert path == []
    finally:
        _cleanup(root)


def test_find_join_path_avoids_cycles():
    root = _mk_workspace_tmp()
    try:
        _write_index(
            root,
            [
                {"from_table": "A.T1", "from_column": "ID", "to_table": "A.T2", "to_column": "ID", "approved": True},
                {"from_table": "A.T2", "from_column": "ID", "to_table": "A.T3", "to_column": "ID", "approved": True},
                {"from_table": "A.T3", "from_column": "ID", "to_table": "A.T1", "to_column": "ID", "approved": True},
            ],
        )
        graph = RelationshipGraph(root / "metadata")
        path = graph.find_join_path(["A.T1"], ["A.T3"])
        assert len(path) <= 3
    finally:
        _cleanup(root)
