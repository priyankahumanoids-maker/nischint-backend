from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "app" / "services" / "safe_route_engine.py"
TEXT = SOURCE.read_text(encoding="utf-8")
TREE = ast.parse(TEXT)


def _load_functions(*names: str):
    wanted = [
        node for node in TREE.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    module = ast.Module(body=wanted, type_ignores=[])
    ast.fix_missing_locations(module)
    ns: dict = {}
    exec(compile(module, str(SOURCE), "exec"), ns, ns)
    return ns


def _route(coords, distance=1000.0, duration=600.0):
    return {
        "distance": distance,
        "duration": duration,
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def test_safe_route_engine_contains_no_synthetic_geometry_generator():
    assert "def _create_variant" not in TEXT
    assert "math.sin" not in TEXT
    assert "math.cos" not in TEXT
    assert "sinusoid" in TEXT  # regression explanation remains explicit


def test_candidate_normalization_never_manufactures_routes():
    ns = _load_functions("_ensure_three_candidates")
    normalize = ns["_ensure_three_candidates"]

    one = _route([[72.90, 19.08], [72.91, 19.09]])
    result = normalize([one])
    assert len(result) == 1
    assert result[0] is one
    assert result[0]["geometry"]["coordinates"] == one["geometry"]["coordinates"]


def test_candidate_normalization_deduplicates_provider_geometry_only():
    ns = _load_functions("_ensure_three_candidates")
    normalize = ns["_ensure_three_candidates"]

    first = _route([[72.90, 19.08], [72.91, 19.09]])
    duplicate = _route([[72.90000001, 19.08000001], [72.91000001, 19.09000001]])
    second = _route([[72.90, 19.08], [72.92, 19.10]])
    result = normalize([first, duplicate, second])
    assert result == [first, second]
