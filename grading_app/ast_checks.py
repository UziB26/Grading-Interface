"""Static Python structure analysis using the AST module only.

Student code is parsed with ``ast.parse`` and inspected via tree walking.
No import, exec, eval, or compile of untrusted code is performed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from grading_app.manifest import StructureRule


@dataclass
class PythonAstProfile:
    imports: set[str]
    function_names: set[str]
    names: set[str]
    attributes: set[str]
    strings: set[str]
    call_names: set[str]


class _PythonAstVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imports: set[str] = set()
        self.function_names: set[str] = set()
        self.names: set[str] = set()
        self.attributes: set[str] = set()
        self.strings: set[str] = set()
        self.call_names: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.add(alias.name.split(".")[0].lower())
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.imports.add(node.module.split(".")[0].lower())
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_names.add(node.name.lower())
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_names.add(node.name.lower())
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self.names.add(node.id.lower())
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.attributes.add(node.attr.lower())
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self.strings.add(node.value.lower())
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.call_names.add(node.func.id.lower())
        elif isinstance(node.func, ast.Attribute):
            self.call_names.add(node.func.attr.lower())
        self.generic_visit(node)


def _contains_token(profile: PythonAstProfile, tokens: Iterable[str]) -> bool:
    token_set = {token.lower() for token in tokens}
    pools = (
        profile.imports,
        profile.function_names,
        profile.names,
        profile.attributes,
        profile.strings,
        profile.call_names,
    )
    for pool in pools:
        if pool & token_set:
            return True
    joined = " ".join(
        sorted(profile.function_names | profile.names | profile.attributes | profile.strings)
    )
    return any(token in joined for token in token_set)


def build_python_ast_profile(source: str, filename: str = "<student>") -> tuple[PythonAstProfile | None, str | None]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return None, f"Syntax error: {exc.msg} (line {exc.lineno})"

    visitor = _PythonAstVisitor()
    visitor.visit(tree)
    return (
        PythonAstProfile(
            imports=visitor.imports,
            function_names=visitor.function_names,
            names=visitor.names,
            attributes=visitor.attributes,
            strings=visitor.strings,
            call_names=visitor.call_names,
        ),
        None,
    )


def evaluate_ast_rule(profile: PythonAstProfile, rule: StructureRule) -> bool:
    rule_type = rule.rule_type.lower()
    if rule_type in {"import_module", "import_from"}:
        modules = {module.lower() for module in rule.modules}
        return bool(modules & profile.imports)
    if rule_type == "token_match":
        return _contains_token(profile, rule.tokens)
    if rule_type == "name":
        names = {name.lower() for name in rule.names}
        return bool(names & profile.names)
    if rule_type == "function_name":
        names = {name.lower() for name in rule.names}
        return bool(names & profile.function_names)
    if rule_type == "call_name":
        names = {name.lower() for name in rule.names}
        return bool(names & profile.call_names)
    if rule_type == "attribute":
        names = {name.lower() for name in rule.names}
        return bool(names & profile.attributes)
    if rule_type == "string_contains":
        joined = " ".join(profile.strings)
        return any(token.lower() in joined for token in rule.tokens)
    return False


def analyze_python_file(path: Path, rules: tuple[StructureRule, ...]) -> tuple[bool, float, int, int, str]:
    source = path.read_text(encoding="utf-8", errors="ignore")
    profile, syntax_error = build_python_ast_profile(source, filename=path.name)
    if profile is None:
        return False, 0.0, 0, len(rules), syntax_error or "Syntax error"

    passed = [rule.label for rule in rules if evaluate_ast_rule(profile, rule)]
    failed = [rule.label for rule in rules if rule.label not in passed]
    total = len(rules)
    passed_count = len(passed)
    score = passed_count / total if total else 1.0
    details = f"AST checks passed {passed_count}/{total}: {', '.join(passed) or 'none'}"
    if failed:
        details += f"; missing: {', '.join(failed)}"
    return True, score, passed_count, total, details
