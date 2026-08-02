from __future__ import annotations

import ast
from pathlib import Path


def test_sql_calls_do_not_build_statements_with_runtime_string_interpolation() -> None:
    source_root = Path(__file__).parents[1] / "src/work_smarter"
    unsafe: list[str] = []

    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            function = node.func
            if not isinstance(function, ast.Attribute) or function.attr not in {
                "execute",
                "executemany",
            }:
                continue
            statement = node.args[0]
            if not isinstance(statement, ast.Constant) or not isinstance(statement.value, str):
                unsafe.append(f"{path.relative_to(source_root)}:{node.lineno}")

    assert unsafe == [], f"SQL statements must be static literals; bind values: {unsafe}"
