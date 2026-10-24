"""Shared deterministic secret redaction for Context and durable evidence."""

import ast
import io
import re
import shlex
import textwrap
import tokenize
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Final, Literal

_SECRET_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{19,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")),
    (
        "secret_assignment",
        re.compile(
            r"""(?i)(["']?\b(?:password|passwd|secret|token|api[_-]?key)\b["']?\s*[:=]\s*["']?)([^\s,;"'}]+)(["']?)"""
        ),
    ),
)
_SECRET_ASSIGNMENT_PATTERN: Final[re.Pattern[str]] = next(
    pattern for kind, pattern in _SECRET_PATTERNS if kind == "secret_assignment"
)

# JavaScript/TypeScript source has no Python AST pass in this detector. Keep the
# conservative assignment rule for literals and unknown expressions, while
# recognizing the common local parsing shape used by the console: a variable
# named ``token`` receives the result of a non-secret string helper. This is a
# source reference, not a credential value. Secret-producing namespaces and
# field names remain excluded so ``token = secrets.token_bytes(...)`` stays
# sensitive.
_SCRIPT_SAFE_TOKEN_CALL: Final[re.Pattern[str]] = re.compile(
    r"(?is)(?P<field>\btoken\b)\s*[:=]\s*"
    r"(?P<object>[A-Za-z_$][\w$]*)\.(?P<method>[A-Za-z_$][\w$]*)\s*\("
)
_SCRIPT_SECRET_OBJECTS: Final[frozenset[str]] = frozenset(
    {"secret", "secrets", "crypto", "credential", "credentials", "auth"}
)
_SCRIPT_SECRET_METHODS: Final[frozenset[str]] = frozenset(
    {"token", "tokenbytes", "tokenhex", "tokenurlsafe", "password", "secret", "key"}
)
_SCRIPT_SAFE_OBJECTS: Final[frozenset[str]] = frozenset(
    {"detail", "metadata", "value", "text", "decoded", "string", "json"}
)
_SCRIPT_SAFE_METHODS: Final[frozenset[str]] = frozenset(
    {"slice", "match", "replace", "trim", "split", "join", "parse", "stringify"}
)

# A source snapshot is code, rather than a log or a URI.  These are the only
# assignment RHS forms that may be treated as references while checking a
# complete source file.  In particular, arbitrary identifiers and dotted
# values remain sensitive: ``token=my.jwt.secret`` may be a real credential.
_SOURCE_REFERENCE_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?P<field>\b(?:password|passwd|secret|token|api[_-]?key)\b)\s*=\s*"
    r"(?P<expression>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+|"
    r"[A-Za-z_]\w*\s*/\s*[\"'][^\"'\r\n]+[\"'])"
    r"(?=\s*(?:[,;\)\]\}]|\r?$|#))",
    re.MULTILINE,
)


def _source_reference(match: re.Match[str]) -> str:
    """Only recognize semantic field references or an explicit file path.

    An arbitrary dotted value is not enough. The terminal attribute must be
    the same field as the assigned argument, and its object must be a single
    name. Path construction requires a filename extension or a path separator.
    No call, indexing, arithmetic other than path division, or interpolation
    is accepted. The full original input is separately checked for key shapes.
    """
    try:
        expression = ast.parse(match["expression"], mode="eval").body
    except (SyntaxError, ValueError, RecursionError, MemoryError, OverflowError):
        return match[0]
    if (
        isinstance(expression, ast.Attribute)
        and isinstance(expression.value, ast.Name)
        and expression.attr.casefold().replace("_", "-")
        == match["field"].casefold().replace("_", "-")
    ) or (
        isinstance(expression, ast.BinOp)
        and isinstance(expression.op, ast.Div)
        and isinstance(expression.left, ast.Name)
        and isinstance(expression.right, ast.Constant)
        and isinstance(expression.right.value, str)
        and re.search(r"(?:[./\\\\])", expression.right.value)
        and not redact_text(expression.right.value).occurrences
    ):
        return "source_reference"
    return match[0]


@dataclass(frozen=True, slots=True)
class RedactionOccurrence:
    """One redaction kind and replacement count."""

    kind: str
    count: int


@dataclass(frozen=True, slots=True)
class RedactedText:
    """Safe text plus non-secret replacement counts."""

    text: str
    occurrences: tuple[RedactionOccurrence, ...]


_MAX_INSPECTION_ENTRIES = 512
_MAX_INSPECTION_BYTES = 16 * 1024 * 1024

type _SourceInspectionKey = tuple[Literal["source", "patch-source", "patch"], str | None, str]
type _GenericInspectionKey = tuple[
    Literal["generic", "generic-body"], tuple[tuple[str, re.Pattern[str]], ...], str
]
type _InspectionKey = _SourceInspectionKey | _GenericInspectionKey


@dataclass(slots=True)
class _SourceInspectionCache:
    # Full text equality is required; path controls the conservative language
    # exception. Generic clean facts additionally bind the actual immutable rules.
    # Only immutable detection facts, never a domain approval, are reused.
    facts: dict[_InspectionKey, tuple[RedactionOccurrence, ...]] = field(default_factory=dict)
    sizes: dict[_InspectionKey, int] = field(default_factory=dict)
    bytes: int = 0
    source_scan_depth: int = 0

    def remember(
        self,
        key: _InspectionKey,
        facts: tuple[RedactionOccurrence, ...],
    ) -> None:
        if _MAX_INSPECTION_ENTRIES < 1:
            return
        generic = key[0] == "generic"
        if generic and len(self.facts) >= _MAX_INSPECTION_ENTRIES:
            return
        # Generic keys reference their rules; only body/path payload is byte-budgeted.
        path = key[1] if isinstance(key[1], str) else ""
        # Avoid a large temporary encoding for keys already over the byte bound.
        available = _MAX_INSPECTION_BYTES - self.bytes if generic else _MAX_INSPECTION_BYTES
        if len(key[2]) + len(path) > available:
            return
        try:
            size = len(key[2].encode("utf-8")) + len(path.encode("utf-8"))
        except UnicodeEncodeError:
            # Memoization cannot add a new rejection to the original detector.
            return
        if size > _MAX_INSPECTION_BYTES:
            return
        if len(self.facts) >= _MAX_INSPECTION_ENTRIES or self.bytes + size > _MAX_INSPECTION_BYTES:
            if generic:
                return
            # Preserve source/patch capacity by evicting only opportunistic generic facts.
            generic_keys = tuple(
                stored
                for stored in self.facts
                if stored[0] == "generic"
                or (key[0] != "generic-body" and stored[0] == "generic-body")
            )
            generic_bytes = sum(self.sizes[stored] for stored in generic_keys)
            if (
                len(self.facts) - len(generic_keys) >= _MAX_INSPECTION_ENTRIES
                or self.bytes - generic_bytes + size > _MAX_INSPECTION_BYTES
            ):
                return
            for stored in generic_keys:
                del self.facts[stored]
                self.bytes -= self.sizes.pop(stored)
                if (
                    len(self.facts) < _MAX_INSPECTION_ENTRIES
                    and self.bytes + size <= _MAX_INSPECTION_BYTES
                ):
                    break
        self.facts[key] = facts
        self.sizes[key] = size
        self.bytes += size


_SOURCE_INSPECTION_CACHE: ContextVar[_SourceInspectionCache | None] = ContextVar(
    "source_inspection_cache", default=None
)
# A parseable hunk is still missing file-wide binding facts. Its pure detection
# facts must never borrow the new complete-body runtime-handle classification.
_PATCH_SOURCE_INSPECTION: ContextVar[bool] = ContextVar("patch_source_inspection", default=False)


@contextmanager
def _source_scan(cache: _SourceInspectionCache | None) -> Iterator[None]:
    """Keep source/patch admission priority without retaining internal generic text."""
    if cache is None:
        yield
        return
    cache.source_scan_depth += 1
    try:
        yield
    finally:
        cache.source_scan_depth -= 1


@contextmanager
def source_inspection_scope() -> Iterator[None]:
    """Bound repeated pure detection scans to one synchronous read lifetime."""
    if _SOURCE_INSPECTION_CACHE.get() is not None:
        yield
        return
    token = _SOURCE_INSPECTION_CACHE.set(_SourceInspectionCache())
    try:
        yield
    finally:
        _SOURCE_INSPECTION_CACHE.reset(token)


def redact_text(content: str) -> RedactedText:
    """Replace supported secret shapes without retaining original values."""
    return _redact_text(content, body=False)


def redact_body_text(content: str) -> RedactedText:
    """Same complete redaction, with clean sealed bodies preceding small generic facts.

    Only a no-match pure fact can be retained. The original shared bounds, exact
    full text/rules and higher source/patch priority remain; no authority is reused.
    """
    return _redact_text(content, body=True)


def _redact_text(content: str, *, body: bool) -> RedactedText:
    cache = _SOURCE_INSPECTION_CACHE.get()
    if cache is not None and cache.source_scan_depth:
        # Internal scans keep their original cost and leave capacity for their parent fact.
        cache = None
    patterns = _SECRET_PATTERNS
    key: _GenericInspectionKey = ("generic-body" if body else "generic", patterns, content)
    if cache is not None and cache.facts.get(key) == ():
        return RedactedText(text=content, occurrences=())
    redacted = content
    occurrences: list[RedactionOccurrence] = []
    for kind, pattern in patterns:
        replacement = (
            rf"\1[REDACTED:{kind}]\3" if kind == "secret_assignment" else f"[REDACTED:{kind}]"
        )
        redacted, count = pattern.subn(replacement, redacted)
        if count:
            occurrences.append(RedactionOccurrence(kind=kind, count=count))
    if cache is not None and not occurrences:
        cache.remember(key, ())
    return RedactedText(text=redacted, occurrences=tuple(occurrences))


def source_secret_occurrences(
    content: str, *, source_path: str | None = None
) -> tuple[RedactionOccurrence, ...]:
    """Inspect complete source, reusing only pure facts within an explicit read scope."""
    cache = _SOURCE_INSPECTION_CACHE.get()
    key: _SourceInspectionKey = (
        "patch-source" if _PATCH_SOURCE_INSPECTION.get() else "source",
        source_path,
        content,
    )
    if cache is not None and (found := cache.facts.get(key)) is not None:
        return found
    with _source_scan(cache):
        result = _inspect_source(content, source_path=source_path)
    if cache is not None:
        cache.remember(key, result)
    return result


def _source_type_reference(node: ast.expr) -> bool:
    """Recognize type syntax without treating a string/call as a type name."""
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _source_type_reference(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _source_type_reference(node.left) and _source_type_reference(node.right)
    if isinstance(node, ast.Subscript):
        return _source_type_reference(node.value) and _source_type_reference(node.slice)
    if isinstance(node, ast.Tuple):
        return all(_source_type_reference(value) for value in node.elts)
    return isinstance(node, ast.Constant) and node.value in (None, Ellipsis)


def _source_root_name(node: ast.expr) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _source_stdlib_imports(tree: ast.Module) -> dict[str, tuple[str, str | None, int]]:
    """Require an exact module-level import with no alias or observed rebinding.

    This is static inspection, not import execution. A parameter, definition,
    assignment, deletion, another import or member mutation anywhere in the file
    conservatively denies that name, including uses in other lexical scopes.
    Imported modules/functions may only occur as exact constructor callees: an
    unknown function argument or container alias could mutate them indirectly.
    """
    allowed: dict[str, tuple[str, str | None, int]] = {}
    trusted_aliases: set[int] = set()
    ambiguous: set[str] = set()
    members = {
        "dataclasses": {"field"},
        "secrets": {"token_bytes", "token_hex", "token_urlsafe"},
        "urllib.parse": {"unquote"},
        "contextvars": {"ContextVar"},
    }
    for statement in tree.body:
        if not isinstance(statement, (ast.Import, ast.ImportFrom)):
            continue
        for alias in statement.names:
            if alias.asname is not None:
                continue
            binding: tuple[str, str | None, int]
            if (
                isinstance(statement, ast.Import)
                and alias.name in members
                and "." not in alias.name
            ):
                import_name, binding = alias.name, (alias.name, None, statement.lineno)
            elif (
                isinstance(statement, ast.ImportFrom)
                and statement.level == 0
                and statement.module in members
                and alias.name in members[statement.module]
            ):
                import_name, binding = (
                    alias.name,
                    (
                        statement.module,
                        alias.name,
                        statement.lineno,
                    ),
                )
            else:
                continue
            if import_name in allowed:
                ambiguous.add(import_name)
            allowed[import_name] = binding
            trusted_aliases.add(id(alias))
    nodes = tuple(ast.walk(tree))
    parents = {child: node for node in nodes for child in ast.iter_child_nodes(node)}
    dynamic_names = {"exec", "eval", "globals", "locals", "__import__", "__builtins__"}
    reflective_names = {"getattr", "setattr", "delattr", "vars"}
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            ambiguous.add(node.id)
        elif isinstance(node, ast.arg):
            ambiguous.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ambiguous.add(node.name)
        elif isinstance(node, ast.alias) and id(node) not in trusted_aliases:
            if node.name == "*":
                ambiguous.update(allowed)
            ambiguous.add(node.asname or node.name.split(".")[0])
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and (
            node.name is not None
        ):
            ambiguous.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest is not None:
            ambiguous.add(node.rest)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Name):
            # A module alias could mutate a generator without writing its import name.
            ambiguous.add(node.value.id)
        elif isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ):
            if (modified := _source_root_name(node)) is not None:
                ambiguous.add(modified)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"exec", "eval"}:
                ambiguous.update(allowed)
            elif node.func.id in {"setattr", "delattr", "vars"} and node.args:
                if (modified := _source_root_name(node.args[0])) is not None:
                    ambiguous.add(modified)
            elif node.func.id in {"globals", "locals"}:
                ambiguous.update(allowed)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            parent = parents.get(node)
            if node.id in dynamic_names or (
                node.id in reflective_names
                and not (isinstance(parent, ast.Call) and parent.func is node)
            ):
                # Aliasing exec/eval or a reflective builtin is still dynamic authority.
                ambiguous.update(allowed)
            if node.id in allowed:
                module, member, _ = allowed[node.id]
                callee: ast.expr = node
                if member is None:
                    if (
                        not isinstance(parent, ast.Attribute)
                        or parent.value is not node
                        or parent.attr not in members[module]
                    ):
                        ambiguous.add(node.id)
                        continue
                    callee = parent
                call = parents.get(callee)
                if (
                    module == "contextvars"
                    and isinstance(call, ast.Subscript)
                    and call.value is callee
                ):
                    declaration = parents.get(call)
                    if (
                        isinstance(declaration, ast.AnnAssign)
                        and declaration.annotation is call
                        and _source_type_reference(call)
                    ):
                        continue
                if not isinstance(call, ast.Call) or call.func is not callee:
                    ambiguous.add(node.id)
        elif isinstance(node, ast.Import) and any(alias.name == "builtins" for alias in node.names):
            # An imported builtin namespace can expose exec even through getattr/aliases.
            ambiguous.update(allowed)
        elif isinstance(node, ast.ImportFrom) and node.module == "builtins":
            if any(alias.name in dynamic_names | reflective_names for alias in node.names):
                ambiguous.update(allowed)
        elif isinstance(node, ast.Attribute) and node.attr in dynamic_names:
            ambiguous.update(allowed)
    decoder_names = {name for name, binding in allowed.items() if binding[0] == "urllib.parse"}
    if decoder_names and _source_url_decoder_has_reflection(nodes):
        ambiguous.update(decoder_names)
    return {name: binding for name, binding in allowed.items() if name not in ambiguous}


def _source_url_decoder_has_reflection(
    nodes: tuple[ast.AST, ...], *, allow_resource_import: bool = False
) -> bool:
    """Deny the new decoder proof at observed module/namespace mutation entrances."""
    reflective_modules = {"sys", "inspect", "importlib", "builtins", "operator", "_operator"}
    reflective_attributes = {
        "__dict__",
        "__globals__",
        "__code__",
        "__closure__",
        "__defaults__",
        "__kwdefaults__",
        "__getattribute__",
        "__getattr__",
        "f_locals",
        "f_globals",
        "_getframe",
        "currentframe",
        "import_module",
        "patch",
        "setattr",
        "delattr",
    }
    return any(
        (
            isinstance(node, ast.Import)
            and any(
                alias.name.split(".")[0] in reflective_modules | {"urllib"} for alias in node.names
            )
        )
        or (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (
                (
                    node.module.split(".")[0] in reflective_modules
                    and not (
                        allow_resource_import
                        and node.module == "importlib.resources"
                        and all(
                            alias.name == "files" and alias.asname is None for alias in node.names
                        )
                    )
                )
                or node.module == "urllib"
                or (
                    node.module == "urllib.parse"
                    and any(
                        alias.name == "unquote" and alias.asname is not None for alias in node.names
                    )
                )
                or node.module == "unittest.mock"
                or (node.module == "unittest" and any(alias.name == "mock" for alias in node.names))
            )
        )
        or (isinstance(node, ast.Attribute) and node.attr in reflective_attributes)
        or (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in {"vars", "patch", "getattr", "setattr", "delattr"}
        )
        for node in nodes
    )


def _source_url_decoded_reference(
    value: ast.expr, field_name: str, imports: dict[str, tuple[str, str | None, int]]
) -> bool:
    """Only exact stdlib unquote of one same-field runtime attribute is proven."""
    if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Name):
        return False
    imported = imports.get(value.func.id)
    if (
        imported is None
        or imported[:2] != ("urllib.parse", "unquote")
        or imported[2] >= value.lineno
        or value.keywords
        or len(value.args) != 1
    ):
        return False
    argument = value.args[0]
    return (
        isinstance(argument, ast.Attribute)
        and isinstance(argument.value, ast.Name)
        and argument.attr.casefold() == field_name.casefold()
    )


def _source_proven_value(
    value: ast.expr,
    field_name: str,
    imports: dict[str, tuple[str, str | None, int]],
    *,
    allow_url_decoder: bool = True,
) -> bool:
    """Allow references or exact stdlib constructors with no credential input."""
    if isinstance(value, ast.Constant) and value.value is None:
        return True
    if (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.attr.casefold() == field_name.casefold()
    ):
        return True
    if (
        isinstance(value, ast.BinOp)
        and isinstance(value.op, ast.Div)
        and isinstance(value.left, ast.Name)
        and isinstance(value.right, ast.Constant)
        and isinstance(value.right.value, str)
        and re.search(r"(?:[./\\\\])", value.right.value)
        and not redact_text(value.right.value).occurrences
    ):
        return True
    if (
        isinstance(value, ast.Subscript)
        and isinstance(value.value, ast.Name)
        and isinstance(value.slice, ast.Constant)
        and value.slice.value == field_name + "_hash"
    ):
        return True
    if not isinstance(value, ast.Call):
        return False
    if allow_url_decoder and _source_url_decoded_reference(value, field_name, imports):
        return True
    if isinstance(value.func, ast.Name):
        imported = imports.get(value.func.id)
        member = imported[1] if imported is not None else None
    elif isinstance(value.func, ast.Attribute) and isinstance(value.func.value, ast.Name):
        imported = imports.get(value.func.value.id)
        member = value.func.attr
        if imported is not None and imported[1] is not None:
            return False
    else:
        return False
    if imported is None or imported[2] >= value.lineno:
        return False
    if imported[0] == "dataclasses" and member == "field":
        return not value.args and all(
            keyword.arg in {"init", "repr", "compare", "hash", "kw_only"}
            and isinstance(keyword.value, ast.Constant)
            and (
                type(keyword.value.value) is bool
                or (keyword.arg == "hash" and keyword.value.value is None)
            )
            for keyword in value.keywords
        )
    return (
        imported[0] == "secrets"
        and member in {"token_bytes", "token_hex", "token_urlsafe"}
        and not value.keywords
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Constant)
        and type(value.args[0].value) is int
        and 1 <= value.args[0].value <= 4096
    )


def _source_runtime_handle_targets(
    tree: ast.Module, imports: dict[str, tuple[str, str | None, int]]
) -> frozenset[ast.Name]:
    """Classify exact nonliteral runtime handles; never evaluate supplied source."""
    nodes = tuple(ast.walk(tree))
    parents = {child: node for node in nodes for child in ast.iter_child_nodes(node)}
    if _source_url_decoder_has_reflection(nodes, allow_resource_import=True) or any(
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id in {"exec", "eval", "globals", "locals", "__import__", "__builtins__"}
        for node in nodes
    ):
        return frozenset()
    scope_types = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.Lambda,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
    )

    def scope_of(node: ast.AST) -> ast.AST:
        parent = parents.get(node)
        while parent is not None and not isinstance(parent, scope_types):
            parent = parents.get(parent)
        return parent if parent is not None else tree

    def unique_name(name: str, scope: ast.AST | None, target: ast.Name) -> bool:
        for node in nodes:
            if (
                isinstance(node, ast.Name)
                and node.id == name
                and (scope is None or scope_of(node) is scope)
                and isinstance(node.ctx, (ast.Store, ast.Del))
                and node is not target
            ):
                return False
            if scope is not None and scope_of(node) is not scope:
                continue
            if (
                (isinstance(node, ast.arg) and node.arg == name)
                or (isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names)
                or (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and node.name == name
                )
                or (
                    isinstance(node, ast.alias)
                    and (node.name == "*" or (node.asname or node.name.split(".")[0]) == name)
                )
                or (
                    isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar))
                    and node.name == name
                )
                or (isinstance(node, ast.MatchMapping) and node.rest == name)
            ):
                return False
        return True

    def external_store_constructor(call: ast.expr | None) -> bool:
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            return False
        owner = scope_of(call)
        if not isinstance(owner, ast.FunctionDef):
            return False
        positional = (*owner.args.posonlyargs, *owner.args.args)
        required = {
            argument.arg for argument in positional[: len(positional) - len(owner.args.defaults)]
        } | {
            argument.arg
            for argument, default in zip(owner.args.kwonlyargs, owner.args.kw_defaults, strict=True)
            if default is None
        }

        def reference(value: ast.expr) -> bool:
            root = value
            while isinstance(root, ast.Attribute) and not root.attr.startswith("_"):
                root = root.value
            return (
                isinstance(root, ast.Name)
                and root.id in required
                and not any(
                    isinstance(node, ast.Name)
                    and node.id == root.id
                    and isinstance(node.ctx, (ast.Store, ast.Del))
                    and scope_of(node) is owner
                    for node in nodes
                )
            )

        def constructor_input(value: ast.expr) -> bool:
            if reference(value):
                return True
            if not (
                isinstance(value, ast.BinOp)
                and isinstance(value.op, ast.Div)
                and isinstance(value.right, ast.Constant)
                and isinstance(value.right.value, str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value.right.value)
                and not redact_text(value.right.value).occurrences
            ):
                return False
            return (
                isinstance(value.left, ast.Attribute)
                and value.left.attr == "root"
                and reference(value.left)
            ) or (isinstance(value.left, ast.BinOp) and constructor_input(value.left))

        if not all(constructor_input(argument) for argument in call.args) or any(
            keyword.arg is None or not constructor_input(keyword.value) for keyword in call.keywords
        ):
            return False
        name = call.func.id
        aliases = [
            alias
            for statement in tree.body
            if isinstance(statement, ast.ImportFrom)
            and statement.level == 0
            and statement.lineno < call.lineno
            for alias in statement.names
            if alias.name == name and alias.asname is None
        ]
        if len(aliases) != 1:
            return False
        for node in nodes:
            if (
                (isinstance(node, ast.Name) and node.id == name)
                and not (
                    isinstance(node.ctx, ast.Load)
                    and isinstance(parent := parents.get(node), ast.Call)
                    and parent.func is node
                )
            ) or (
                (isinstance(node, ast.arg) and node.arg == name)
                or (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and node.name == name
                )
                or (
                    isinstance(node, ast.alias)
                    and node is not aliases[0]
                    and (node.name == "*" or (node.asname or node.name.split(".")[0]) == name)
                )
            ):
                return False
        return True

    def unambiguous_store(scope: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        initializers = 0
        for node in nodes:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in {"claim", "store"}
            ) or (
                isinstance(node, ast.Name)
                and node.id in {"claim", "store"}
                and isinstance(node.ctx, (ast.Store, ast.Del))
            ):
                return False
            if not isinstance(node, ast.Attribute):
                continue
            if node.attr == "claim" and isinstance(node.ctx, (ast.Store, ast.Del)):
                return False
            if not (
                node.attr == "store"
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
            ):
                continue
            parent = parents.get(node)
            if isinstance(node.ctx, ast.Load):
                if not (isinstance(parent, ast.Attribute) and parent.value is node):
                    return False
                continue
            owner = scope_of(node)
            if not (
                isinstance(node.ctx, ast.Store)
                and isinstance(parent, ast.Assign)
                and parent.targets == [node]
                and isinstance(owner, ast.FunctionDef)
                and owner.name == "__init__"
                and scope_of(owner) is scope_of(scope)
                and parent in owner.body
                and external_store_constructor(parent.value)
            ):
                return False
            initializers += 1
        return initializers <= 1

    context_imports = {
        name: binding for name, binding in imports.items() if binding[0] == "contextvars"
    }
    # A second module alias can mutate a constructor through another spelling.
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            aliases = [
                alias
                for alias in node.names
                if (
                    (isinstance(node, ast.Import) and alias.name == "contextvars")
                    or (isinstance(node, ast.ImportFrom) and node.module == "contextvars")
                )
            ]
            if aliases and any(
                (alias.asname or alias.name) not in context_imports for alias in aliases
            ):
                context_imports.clear()
                break
    instances: dict[str, int] = {}
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)) or not isinstance(
            statement.value, ast.Call
        ):
            continue
        target = (
            statement.target
            if isinstance(statement, ast.AnnAssign)
            else statement.targets[0]
            if len(statement.targets) == 1
            else None
        )
        call = statement.value
        if not isinstance(target, ast.Name) or not unique_name(target.id, None, target):
            continue
        callee = call.func
        imported = context_imports.get(callee.id) if isinstance(callee, ast.Name) else None
        if (
            isinstance(callee, ast.Attribute)
            and isinstance(callee.value, ast.Name)
            and callee.attr == "ContextVar"
        ):
            module = context_imports.get(callee.value.id)
            imported = module if module is not None and module[1] is None else None
        if (
            imported is None
            or imported[2] >= statement.lineno
            or (imported[1] not in {None, "ContextVar"})
        ):
            continue
        if (
            len(call.args) != 1
            or not isinstance(call.args[0], ast.Constant)
            or not isinstance(call.args[0].value, str)
            or not call.args[0].value
            or len(call.args[0].value) > 256
            or redact_text(call.args[0].value).occurrences
            or len(call.keywords) > 1
            or any(
                keyword.arg != "default"
                or not isinstance(keyword.value, ast.Constant)
                or keyword.value.value is not None
                for keyword in call.keywords
            )
        ):
            continue
        valid = True
        for node in nodes:
            if (isinstance(node, ast.arg) and node.arg == target.id) or (
                isinstance(node, (ast.Global, ast.Nonlocal)) and target.id in node.names
            ):
                valid = False
                break
            if not isinstance(node, ast.Name) or node.id != target.id or node is target:
                continue
            member = parents.get(node)
            invocation = parents.get(member) if member is not None else None
            if not (
                isinstance(node.ctx, ast.Load)
                and isinstance(member, ast.Attribute)
                and member.value is node
                and member.attr in {"get", "set", "reset"}
                and isinstance(invocation, ast.Call)
                and invocation.func is member
                and not invocation.keywords
                and (
                    not invocation.args
                    if member.attr == "get"
                    else len(invocation.args) == 1 and isinstance(invocation.args[0], ast.Name)
                )
            ):
                valid = False
                break
        if valid:
            instances[target.id] = statement.lineno
    result: set[ast.Name] = set()
    for assignment in nodes:
        if not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1:
            continue
        target = assignment.targets[0]
        scope = scope_of(assignment)
        if not isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(target, ast.Name):
            setter = assignment.value
            if (
                isinstance(setter, ast.Call)
                and isinstance(setter.func, ast.Attribute)
                and isinstance(setter.func.value, ast.Name)
                and setter.func.value.id in instances
                and instances[setter.func.value.id] < assignment.lineno
                and setter.func.attr == "set"
                and len(setter.args) == 1
                and isinstance(setter.args[0], ast.Name)
                and not setter.keywords
                and unique_name(target.id, scope, target)
                and assignment in scope.body
            ):
                result.add(target)
            continue
        if (
            not isinstance(target, ast.Tuple)
            or not all(isinstance(item, ast.Name) for item in target.elts)
            or not isinstance(assignment.value, ast.Name)
        ):
            continue
        names = tuple(item for item in target.elts if isinstance(item, ast.Name))
        if (
            len(names) < 2
            or len({item.id for item in names}) != len(names)
            or not all(unique_name(item.id, scope, item) for item in names)
        ):
            continue
        value = assignment.value
        writers = [
            node
            for node in nodes
            if isinstance(node, ast.Name)
            and node.id == value.id
            and isinstance(node.ctx, ast.Store)
            and scope_of(node) is scope
        ]
        if len(writers) != 1 or not unique_name(value.id, scope, writers[0]):
            continue
        binding = parents.get(writers[0])
        if not (
            isinstance(binding, ast.Assign)
            and binding.targets == [writers[0]]
            and parents.get(binding) is parents.get(assignment)
            and binding.lineno < assignment.lineno
            and isinstance(binding.value, ast.Call)
            and not binding.value.args
            and isinstance(binding.value.func, ast.Attribute)
            and binding.value.func.attr == "claim"
            and isinstance(binding.value.func.value, ast.Attribute)
            and binding.value.func.value.attr == "store"
            and isinstance(binding.value.func.value.value, ast.Name)
            and binding.value.func.value.value.id == "self"
            and isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef))
            and bool(scope.args.posonlyargs or scope.args.args)
            and (*scope.args.posonlyargs, *scope.args.args)[0].arg == "self"
            and unambiguous_store(scope)
        ):
            continue
        if any(
            (
                isinstance(node, ast.Name)
                and node.id == "self"
                and isinstance(node.ctx, (ast.Store, ast.Del))
            )
            or (
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, (ast.Store, ast.Del))
                and (
                    (
                        isinstance(node.value, ast.Name)
                        and node.value.id == "self"
                        and node.attr == "store"
                    )
                    or (
                        isinstance(node.value, ast.Attribute)
                        and isinstance(node.value.value, ast.Name)
                        and node.value.value.id == "self"
                        and node.value.attr == "store"
                    )
                )
            )
            for node in nodes
            if scope_of(node) is scope
        ) or any(
            keyword.arg is None
            or not (
                (
                    isinstance(keyword.value, ast.Attribute)
                    and isinstance(keyword.value.value, ast.Name)
                    and keyword.value.value.id == "self"
                )
                or (
                    isinstance(keyword.value, ast.Call)
                    and not keyword.value.args
                    and not keyword.value.keywords
                    and isinstance(keyword.value.func, ast.Attribute)
                    and isinstance(keyword.value.func.value, ast.Name)
                    and keyword.value.func.value.id == "self"
                    and keyword.value.func.attr == "clock"
                )
            )
            for keyword in binding.value.keywords
        ):
            continue
        # Do not borrow a closure/alias or consume a value that an unknown call may mutate.
        references = [
            node
            for node in nodes
            if isinstance(node, ast.Name) and node.id == value.id and isinstance(node.ctx, ast.Load)
        ]
        if any(
            scope_of(node) is not scope
            or (
                node is not value
                and not (
                    isinstance(parent := parents.get(node), ast.Compare)
                    and parent.left is node
                    and len(parent.ops) == 1
                    and isinstance(parent.ops[0], ast.Is)
                    and len(parent.comparators) == 1
                    and isinstance(parent.comparators[0], ast.Constant)
                    and parent.comparators[0].value is None
                )
            )
            for node in references
        ):
            continue
        result.update(names)
    return frozenset(result)


def _source_assignment_facts(
    tree: ast.Module, content: str, lines: list[str], offsets: list[int]
) -> tuple[frozenset[int], tuple[RedactionOccurrence, ...]]:
    """Mask only syntactic field declarations; inspect each default/RHS separately."""
    imports = _source_stdlib_imports(tree)
    runtime_handles = (
        frozenset()
        if _PATCH_SOURCE_INSPECTION.get()
        else _source_runtime_handle_targets(tree, imports)
    )
    safe_starts: set[int] = set()
    extra: list[RedactionOccurrence] = []

    def field_start(name: str, node: ast.expr | ast.arg | ast.keyword) -> int | None:
        if not re.fullmatch(r"(?i)(?:password|passwd|secret|token|api[_-]?key)", name):
            return None
        # AST columns count UTF-8 bytes; tokenize and regex columns count characters.
        prefix = lines[node.lineno - 1].encode("utf-8")[: node.col_offset].decode("utf-8")
        return offsets[node.lineno - 1] + len(prefix)

    def annotation(
        name: str, node: ast.expr | ast.arg, declared: ast.expr | None, value: ast.expr | None
    ) -> None:
        start = field_start(name, node)
        if start is None or declared is None or not _source_type_reference(declared):
            return
        safe_starts.add(start)
        if value is not None and not _source_proven_value(
            value, name, imports, allow_url_decoder=not isinstance(node, ast.arg)
        ):
            expression = ast.get_source_segment(content, value)
            if expression is None:
                extra.append(RedactionOccurrence("secret_assignment", 1))
            else:
                extra.extend(redact_text(name + "=" + expression).occurrences)

    for target in runtime_handles:
        if (start := field_start(target.id, target)) is not None:
            safe_starts.add(start)
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            annotation(node.target.id, node.target, node.annotation, node.value)
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target = node.targets[0]
            start = field_start(target.id, target)
            if start is not None and _source_proven_value(node.value, target.id, imports):
                safe_starts.add(start)
        elif (
            isinstance(node, ast.keyword)
            and node.arg is not None
            and _source_url_decoded_reference(node.value, node.arg, imports)
        ):
            if (start := field_start(node.arg, node)) is not None:
                safe_starts.add(start)
        elif isinstance(node, ast.arguments):
            positional = (*node.posonlyargs, *node.args)
            default_offset = len(positional) - len(node.defaults)
            for index, argument in enumerate(positional):
                default = node.defaults[index - default_offset] if index >= default_offset else None
                annotation(argument.arg, argument, argument.annotation, default)
            for argument, default in zip(node.kwonlyargs, node.kw_defaults, strict=True):
                annotation(argument.arg, argument, argument.annotation, default)
            for variadic_argument in (node.vararg, node.kwarg):
                if variadic_argument is not None:
                    annotation(
                        variadic_argument.arg, variadic_argument, variadic_argument.annotation, None
                    )
    return frozenset(safe_starts), tuple(extra)


def _source_dynamic_interpolation_spans(
    tree: ast.Module, content: str, lines: list[str], offsets: list[int]
) -> frozenset[tuple[int, int]]:
    """Prove exact runtime credential interpolation, without masking a string.

    Only a direct single-writer binding in the same ordinary lexical scope can
    establish provenance. This does not execute Python or confer authority on
    arbitrary expressions, closures, parameters or source-looking log text.
    """
    imports = _source_stdlib_imports(tree)
    if not imports:
        return frozenset()
    nodes = tuple(ast.walk(tree))
    parents = {child: node for node in nodes for child in ast.iter_child_nodes(node)}
    scope_kinds = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.Lambda,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
    )

    def scope_of(node: ast.AST) -> ast.AST:
        parent = parents.get(node)
        while parent is not None and not isinstance(parent, scope_kinds):
            parent = parents.get(parent)
        return parent if parent is not None else tree

    # These observed reflective entrances can mutate constructor/name bindings
    # without an AST Store. Existing exec/eval/globals/locals checks also apply.
    reflective_modules = {"sys", "inspect", "importlib", "builtins"}
    reflective_attributes = {"f_locals", "f_globals", "_getframe", "currentframe", "import_module"}
    if any(
        (
            isinstance(node, ast.Import)
            and any(alias.name.split(".")[0] in reflective_modules for alias in node.names)
        )
        or (
            isinstance(node, ast.ImportFrom)
            and (
                node.module is not None
                and (
                    node.module.split(".")[0] in reflective_modules
                    or node.module == "unittest.mock"
                    or (
                        node.module == "unittest"
                        and any(alias.name == "mock" for alias in node.names)
                    )
                )
            )
        )
        or (
            isinstance(node, ast.Attribute)
            and (
                node.attr in reflective_attributes
                or (
                    node.attr in {"patch", "setattr", "delattr"}
                    and (
                        not isinstance(call := parents.get(node), ast.Call)
                        or call.func is not node
                        or node.attr == "patch"
                        or not call.args
                        or not isinstance(call.args[0], ast.Name)
                        or call.args[0].id in imports
                    )
                )
            )
        )
        or (isinstance(node, ast.Name) and node.id == "vars" and isinstance(node.ctx, ast.Load))
        # Common test monkeypatch APIs can rewrite the trusted constructor even
        # when their target is assembled from string fragments. A typed call is
        # enough to revoke this narrow proof; unknown calls remain conservative
        # through the ordinary source scanner.
        or (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"patch", "setattr"}
        )
        or (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and (node.value == "secrets" or node.value.startswith("secrets."))
        )
        for node in nodes
    ):
        return frozenset()
    scopes = {node: scope_of(node) for node in nodes}
    writers_by_name: dict[tuple[ast.AST, str], list[ast.Name]] = {}
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            writers_by_name.setdefault((scopes[node], node.id), []).append(node)
    ambiguous_bindings: dict[tuple[ast.AST, str], bool] = {}
    result: set[tuple[int, int]] = set()
    for interpolation in nodes:
        if not (
            isinstance(interpolation, ast.FormattedValue)
            and isinstance(interpolation.value, ast.Name)
            and interpolation.conversion == -1
            and interpolation.format_spec is None
        ):
            continue
        joined = parents.get(interpolation)
        if not (
            isinstance(joined, ast.JoinedStr)
            and len(joined.values) == 2
            and isinstance(joined.values[0], ast.Constant)
            and joined.values[1] is interpolation
        ):
            continue
        name = interpolation.value.id
        if ast.get_source_segment(content, interpolation) != "{" + name + "}":
            continue
        scope = scopes[interpolation]
        if not isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Default arguments/decorators and conditional bindings are not body facts.
        statement: ast.AST = interpolation
        while parents.get(statement) is not scope:
            parent = parents.get(statement)
            if parent is None:
                break
            statement = parent
        if statement not in scope.body:
            continue
        writers = writers_by_name.get((scope, name), [])
        if len(writers) != 1:
            continue
        target = writers[0]
        binding = parents.get(target)
        if not (
            isinstance(binding, ast.Assign)
            and binding in scope.body
            and scope.body.index(binding) < scope.body.index(statement)
            and isinstance(binding.value, ast.Call)
            and binding.targets == [target]
        ):
            continue
        key = scope, name
        if key not in ambiguous_bindings:
            ambiguous_bindings[key] = False
            scope_nodes: tuple[ast.AST, ...] = tuple(ast.walk(scope))
        else:
            if ambiguous_bindings[key]:
                continue
            # A repeated interpolation of the same binding reuses only its
            # syntactic ambiguity fact, never a domain admission or verdict.
            scope_nodes = ()
        for node in scope_nodes:
            if (
                (isinstance(node, ast.arg) and node.arg == name)
                or (isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names)
                or (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and node is not scope
                    and node.name == name
                )
                or (
                    isinstance(node, ast.alias)
                    and (node.name == "*" or (node.asname or node.name.split(".")[0]) == name)
                )
                or (
                    isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar))
                    and node.name == name
                )
                or (isinstance(node, ast.MatchMapping) and node.rest == name)
                or (isinstance(node, ast.Name) and node.id == name and scopes[node] is not scope)
            ):
                ambiguous_bindings[key] = True
                break
        if ambiguous_bindings[key]:
            continue
        call = binding.value
        callee = call.func.value if isinstance(call.func, ast.Attribute) else call.func
        imported = imports.get(callee.id) if isinstance(callee, ast.Name) else None
        if (
            imported is None
            or imported[0] != "secrets"
            or not _source_proven_value(call, "", imports)
        ):
            continue
        if interpolation.end_lineno is None or interpolation.end_col_offset is None:
            continue
        start = offsets[interpolation.lineno - 1] + len(
            lines[interpolation.lineno - 1]
            .encode("utf-8")[: interpolation.col_offset]
            .decode("utf-8")
        )
        end = offsets[interpolation.end_lineno - 1] + len(
            lines[interpolation.end_lineno - 1]
            .encode("utf-8")[: interpolation.end_col_offset]
            .decode("utf-8")
        )
        result.add((start, end))
    return frozenset(result)


def _inspect_source(
    content: str, *, source_path: str | None = None
) -> tuple[RedactionOccurrence, ...]:
    """Check bounded source while preserving safe reference expressions.

    Complete retained source must remain byte-for-byte identical.  We therefore
    replace only the narrowly recognized reference spans in a temporary value,
    run the ordinary conservative detector, and return occurrence facts only.
    No raw sensitive text is returned as a supposedly redacted value. The generic detector remains
    unchanged for every other text boundary.
    """
    detected = redact_text(content).occurrences
    if not any(occurrence.kind == "secret_assignment" for occurrence in detected):
        return detected
    if source_path is not None and source_path.casefold().endswith(
        (".js", ".jsx", ".ts", ".tsx")
    ):
        # The complete-source detector intentionally has no JavaScript parser.
        # Mask only a small, typed family of local string-parser calls before
        # applying the generic assignment rule. Unknown objects/methods and all
        # secret-producing names remain conservative. This also keeps comments
        # and string literals protected because the generic scan still sees any
        # assignment outside these exact source shapes.
        safe_spans: list[tuple[int, int]] = []
        for match in _SCRIPT_SAFE_TOKEN_CALL.finditer(content):
            object_name = match["object"].casefold()
            method_name = match["method"].casefold()
            if (
                object_name in _SCRIPT_SAFE_OBJECTS
                and method_name in _SCRIPT_SAFE_METHODS
                and object_name not in _SCRIPT_SECRET_OBJECTS
                and method_name not in _SCRIPT_SECRET_METHODS
            ):
                line_start = content.rfind("\n", 0, match.start()) + 1
                line_end = content.find("\n", match.end())
                safe_spans.append((line_start, len(content) if line_end < 0 else line_end))
        if safe_spans:
            chars = list(content)
            for start, end in safe_spans:
                chars[start:end] = "source_reference".ljust(end - start, " ")
            content = "".join(chars)
            detected = redact_text(content).occurrences
            if not any(occurrence.kind == "secret_assignment" for occurrence in detected):
                return detected
    if (
        source_path is None
        or not source_path.endswith(".py")
        or redact_text(source_path).occurrences
    ):
        return detected
    try:
        # Syntax is inspected, never evaluated. Unknown/incomplete source gets
        # no exception; quotes/comments cannot manufacture a field reference.
        tree = ast.parse(content)
        tokens = tuple(tokenize.generate_tokens(io.StringIO(content).readline))
    except (
        SyntaxError,
        ValueError,
        tokenize.TokenError,
        IndentationError,
        RecursionError,
        MemoryError,
        OverflowError,
        UnicodeError,
    ):
        return redact_text(content).occurrences
    lines = content.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    try:
        safe_starts, extra = _source_assignment_facts(tree, content, lines, offsets)
        dynamic_spans = _source_dynamic_interpolation_spans(tree, content, lines, offsets)
    except (ValueError, RecursionError, MemoryError, OverflowError, UnicodeError):
        return detected
    excluded: list[tuple[int, int]] = []
    interpolated: list[int] = []
    for token in tokens:
        start = offsets[token.start[0] - 1] + token.start[1]
        end = offsets[token.end[0] - 1] + token.end[1]
        kind = tokenize.tok_name[token.type]
        if kind in {"FSTRING_START", "TSTRING_START"}:
            interpolated.append(start)
        elif kind in {"FSTRING_END", "TSTRING_END"} and interpolated:
            beginning = interpolated.pop()
            excluded.append((beginning, end))
        elif token.type in {tokenize.STRING, tokenize.COMMENT}:
            excluded.append((start, end))
    excluded.sort()
    excluded_index = 0

    def protect(match: re.Match[str]) -> str:
        nonlocal excluded_index
        # The assignment detector excludes the final brace; require the exact
        # proven AST span, rather than exempting any containing string token.
        if (match.start(2), match.end(2) + 1) in dynamic_spans:
            return "source_reference"
        while excluded_index < len(excluded) and excluded[excluded_index][1] <= match.start():
            excluded_index += 1
        if excluded_index < len(excluded) and excluded[excluded_index][0] <= match.start():
            return match[0]
        if match.start() in safe_starts:
            return "source_reference"
        reference = _SOURCE_REFERENCE_ASSIGNMENT.match(content, match.start())
        if reference is not None and _source_reference(reference) != reference[0]:
            return "source_reference"
        return match[0]

    # Never mask a credential inside an otherwise valid reference/path span.
    strong = tuple(
        RedactionOccurrence(kind=kind, count=len(pattern.findall(content)))
        for kind, pattern in _SECRET_PATTERNS
        if kind != "secret_assignment" and pattern.search(content)
    )
    protected = _SECRET_ASSIGNMENT_PATTERN.sub(protect, content)
    assignments = tuple(
        occurrence
        for occurrence in redact_text(protected).occurrences
        if occurrence.kind == "secret_assignment"
    )
    return (*strong, *assignments, *extra)


def patch_secret_occurrences(content: str) -> tuple[RedactionOccurrence, ...]:
    """Inspect complete hunks with a separate, read-scoped patch cache namespace."""
    cache = _SOURCE_INSPECTION_CACHE.get()
    key: _SourceInspectionKey = ("patch", None, content)
    if cache is not None and (found := cache.facts.get(key)) is not None:
        return found
    with _source_scan(cache):
        result = _inspect_patch(content)
    if cache is not None:
        cache.remember(key, result)
    return result


def _inspect_patch(content: str) -> tuple[RedactionOccurrence, ...]:
    """Inspect code hunk sides separately; headers and unknown patches stay generic.

    Never infer a language from arbitrary leading +/- characters. Only explicit
    Git diff headers and real hunk headers select the supported Python mode.
    Partial hunks that cannot be parsed remain conservatively sensitive.
    """
    metadata: list[str] = []
    old_lines: list[str] = []
    new_lines: list[str] = []
    paths: tuple[str, str] | None = None
    in_hunk = False
    remaining: tuple[int, int] | None = None
    invalid = False
    occurrences: list[RedactionOccurrence] = []

    def flush() -> None:
        nonlocal invalid, remaining
        if remaining is not None and remaining != (0, 0):
            invalid = True
        remaining = None
        for body, path in (
            (old_lines, paths[0] if paths else None),
            (new_lines, paths[1] if paths else None),
        ):
            if body:
                inspection_binding = _PATCH_SOURCE_INSPECTION.set(True)
                try:
                    occurrences.extend(
                        source_secret_occurrences(textwrap.dedent("".join(body)), source_path=path)
                    )
                finally:
                    _PATCH_SOURCE_INSPECTION.reset(inspection_binding)
        old_lines.clear()
        new_lines.clear()

    for line in content.splitlines(keepends=True):
        if line.startswith("diff --git "):
            flush()
            in_hunk = False
            try:
                names = shlex.split(line.rstrip("\r\n"))
                paths = (
                    (names[2][2:], names[3][2:])
                    if len(names) == 4 and names[2].startswith("a/") and names[3].startswith("b/")
                    else None
                )
            except ValueError:
                paths = None
            metadata.append(line)
        elif match := re.match(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@(?:\r?\n)?$", line):
            flush()
            in_hunk = paths is not None
            if any(value is not None and len(value) > 7 for value in (match[1], match[2])):
                return redact_text(content).occurrences
            remaining = (
                int(match[1]) if match[1] is not None else 1,
                int(match[2]) if match[2] is not None else 1,
            )
            metadata.append(line)
        elif in_hunk and line[:1] in {"+", "-", " "}:
            if remaining is None:
                invalid = True
            else:
                remaining = (
                    remaining[0] - (line[0] != "+"),
                    remaining[1] - (line[0] != "-"),
                )
                if min(remaining) < 0:
                    invalid = True
            if line[0] != "+":
                old_lines.append(line[1:])
            if line[0] != "-":
                new_lines.append(line[1:])
        elif in_hunk and line.startswith("\\ No newline at end of file"):
            pass
        else:
            flush()
            in_hunk = False
            metadata.append(line)
    flush()
    if invalid:
        return redact_text(content).occurrences
    occurrences.extend(redact_text("".join(metadata)).occurrences)
    return tuple(occurrences)


__all__ = [
    "RedactedText",
    "RedactionOccurrence",
    "patch_secret_occurrences",
    "redact_text",
    "source_secret_occurrences",
]
