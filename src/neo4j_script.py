"""
Build a Neo4j knowledge graph from a Python repository.

Usage:
    python src/neo4j_script.py /path/to/repo
    python src/neo4j_script.py /path/to/repo --neo4j-uri bolt://localhost:7687

Requires NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD in .env or environment.
"""

import argparse
import ast
import hashlib
import logging
import os
import sys
from dataclasses import dataclass, field

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

IGNORE_DIRS = {
    ".git", "__pycache__", ".pytest_cache",
    ".venv", ".venv_testing", "venv", "env",
    "node_modules", "dist", "build",
    ".chunk_cache", ".temp_testing",
    ".tox", "htmlcov", ".mypy_cache", ".ruff_cache",
    ".eggs", "*.egg-info",
}

# Extensions to index as File nodes (no symbol extraction for non-Python)
INDEXABLE_EXTENSIONS = {
    ".py", ".pyi",
    ".txt", ".md", ".rst",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".sh", ".bash",
    ".dockerfile",
}
INDEXABLE_FILENAMES = {
    "Makefile", "Dockerfile", "Procfile",
    "requirements.txt", "setup.py", "setup.cfg", "pyproject.toml",
    "tox.ini", "Pipfile", "Pipfile.lock", "poetry.lock",
    ".gitignore", ".dockerignore",
}


def lang_for_path(path: str) -> str:
    """Return a language tag for the file, or 'text' as fallback."""
    ext_map = {
        ".py": "python", ".pyi": "python",
        ".json": "json", ".yaml": "yaml", ".yml": "yaml",
        ".toml": "toml", ".ini": "ini", ".cfg": "ini",
        ".md": "markdown", ".rst": "rst", ".txt": "text",
        ".sh": "shell", ".bash": "shell",
    }
    _, ext = os.path.splitext(path)
    return ext_map.get(ext, "text")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SymbolInfo:
    name: str
    kind: str           # "class", "function", "method", "constant"
    lineno: int | None
    parent_class: str | None = None
    params: list[str] = field(default_factory=list)
    return_annotation: str | None = None
    decorators: list[str] = field(default_factory=list)
    docstring: str | None = None
    bases: list[str] = field(default_factory=list)  # for classes only

    def fqn(self, file_path: str) -> str:
        if self.parent_class:
            return f"{file_path}:{self.parent_class}.{self.name}"
        return f"{file_path}:{self.name}"


@dataclass
class ImportInfo:
    type: str           # "import" or "importfrom"
    module: str | None  # e.g. "os.path" or None for `from . import X`
    level: int          # 0 = absolute, 1 = ., 2 = .., etc.
    names: list[dict]   # [{"name": "X", "asname": "Y"}, ...]
    lineno: int | None = None


@dataclass
class ResolvedImport:
    target_file: str | None    # relative path within repo, or None if external
    symbols: list[str]         # symbol names imported
    kind: str                  # "internal", "external"
    raw: str                   # human-readable form for debugging
    module_name: str | None    # original module name (for ExternalDep)


@dataclass
class FileInfo:
    rel_path: str
    rel_dir: str
    lang: str
    file_hash: str
    line_count: int
    size_bytes: int
    symbols: list[SymbolInfo] = field(default_factory=list)
    imports: list[ImportInfo] = field(default_factory=list)
    resolved_imports: list[ResolvedImport] = field(default_factory=list)


# ---------------------------------------------------------------------------
# File iteration
# ---------------------------------------------------------------------------

def iter_files(root: str):
    """Yield absolute paths of indexable files, skipping ignored directories."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORE_DIRS and not d.endswith(".egg-info")
        ]
        for fn in filenames:
            _, ext = os.path.splitext(fn)
            if ext in INDEXABLE_EXTENSIONS or fn in INDEXABLE_FILENAMES:
                yield os.path.join(dirpath, fn)


# ---------------------------------------------------------------------------
# Python AST parsing
# ---------------------------------------------------------------------------

def _safe_unparse(node) -> str:
    """Safely unparse an AST node to string."""
    try:
        return ast.unparse(node)
    except Exception:
        return "?"


def parse_python(path: str, repo_root: str) -> tuple[list[SymbolInfo], list[ImportInfo], str, int, int]:
    """
    Parse a Python file and extract symbols + imports.

    Returns: (symbols, imports, file_hash, line_count, size_bytes)
    """
    with open(path, "rb") as f:
        data = f.read()

    text = data.decode("utf-8", errors="replace")
    tree = ast.parse(text, filename=path)
    file_hash = hashlib.sha256(data).hexdigest()
    line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    size_bytes = len(data)

    symbols: list[SymbolInfo] = []
    imports: list[ImportInfo] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self._class_stack: list[str] = []

        @property
        def current_class(self) -> str | None:
            return self._class_stack[-1] if self._class_stack else None

        def visit_ClassDef(self, node: ast.ClassDef):
            bases = [_safe_unparse(b) for b in node.bases]
            decorators = [_safe_unparse(d) for d in node.decorator_list]
            docstring = ast.get_docstring(node)
            symbols.append(SymbolInfo(
                name=node.name,
                kind="class",
                lineno=node.lineno,
                parent_class=self.current_class,
                decorators=decorators,
                docstring=docstring,
                bases=bases,
            ))
            self._class_stack.append(node.name)
            self.generic_visit(node)
            self._class_stack.pop()

        def _visit_func(self, node):
            kind = "method" if self.current_class else "function"
            params = []
            for arg in node.args.args:
                if arg.arg == "self" or arg.arg == "cls":
                    continue
                params.append(arg.arg)
            ret = _safe_unparse(node.returns) if node.returns else None
            decorators = [_safe_unparse(d) for d in node.decorator_list]
            docstring = ast.get_docstring(node)
            symbols.append(SymbolInfo(
                name=node.name,
                kind=kind,
                lineno=node.lineno,
                parent_class=self.current_class,
                params=params,
                return_annotation=ret,
                decorators=decorators,
                docstring=docstring,
            ))
            # Visit nested classes but not nested functions (too noisy)
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    self.visit(child)

        def visit_FunctionDef(self, node):
            self._visit_func(node)

        def visit_AsyncFunctionDef(self, node):
            self._visit_func(node)

        def visit_Assign(self, node: ast.Assign):
            # Only capture module-level or class-level constants
            if self._class_stack:
                return  # skip class-level attrs for now (too noisy)
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    symbols.append(SymbolInfo(
                        name=target.id,
                        kind="constant",
                        lineno=node.lineno,
                    ))

        def visit_Import(self, node: ast.Import):
            for alias in node.names:
                imports.append(ImportInfo(
                    type="import",
                    module=alias.name,
                    level=0,
                    names=[{"name": alias.name, "asname": alias.asname}],
                    lineno=node.lineno,
                ))

        def visit_ImportFrom(self, node: ast.ImportFrom):
            imports.append(ImportInfo(
                type="importfrom",
                module=node.module,
                level=node.level or 0,
                names=[{"name": a.name, "asname": a.asname} for a in node.names],
                lineno=node.lineno,
            ))

    Visitor().visit(tree)
    return symbols, imports, file_hash, line_count, size_bytes


# ---------------------------------------------------------------------------
# Import resolution
# ---------------------------------------------------------------------------

def _try_resolve_module_path(mod_path: str, repo_root: str) -> str | None:
    """
    Given a '/'-separated module path (e.g. 'pkg/sub/mod'), try to find the
    corresponding file in the repo. Checks:
      1. mod_path.py
      2. mod_path/__init__.py
    Returns relative path or None.
    """
    cand1 = os.path.join(repo_root, mod_path + ".py")
    if os.path.isfile(cand1):
        return os.path.relpath(cand1, repo_root).replace("\\", "/")

    cand2 = os.path.join(repo_root, mod_path, "__init__.py")
    if os.path.isfile(cand2):
        return os.path.relpath(cand2, repo_root).replace("\\", "/")

    return None


def resolve_import(
    imp: ImportInfo,
    importing_file: str,
    repo_root: str,
) -> list[ResolvedImport]:
    """
    Resolve an import to target file(s) within the repo.

    Args:
        imp: Parsed import info
        importing_file: Relative path of the file containing the import
        repo_root: Absolute path to repo root

    Returns:
        List of ResolvedImport (may be multiple for `from X import Y, Z`
        where Y and Z are submodules)
    """
    results: list[ResolvedImport] = []
    symbol_names = [n["name"] for n in imp.names]

    # Build human-readable raw string
    if imp.type == "import":
        raw = f"import {imp.module}"
    else:
        dots = "." * imp.level
        mod_str = imp.module or ""
        names_str = ", ".join(
            f"{n['name']}" + (f" as {n['asname']}" if n.get("asname") else "")
            for n in imp.names
        )
        raw = f"from {dots}{mod_str} import {names_str}"

    # --- Determine the base module path ---
    if imp.level > 0:
        # Relative import: compute base directory from importing file
        importing_dir = os.path.dirname(importing_file)
        parts = importing_dir.split("/") if importing_dir else []

        # Go up (level - 1) directories. Level 1 = current package, level 2 = parent, etc.
        levels_up = imp.level - 1
        if levels_up > len(parts):
            # Invalid relative import (goes above repo root)
            results.append(ResolvedImport(
                target_file=None, symbols=symbol_names,
                kind="external", raw=raw, module_name=raw,
            ))
            return results

        base_parts = parts[:len(parts) - levels_up] if levels_up > 0 else parts
        base_dir = "/".join(base_parts)

        if imp.module:
            mod_path = (base_dir + "/" + imp.module.replace(".", "/")).strip("/")
        else:
            mod_path = base_dir
    else:
        # Absolute import
        if not imp.module:
            return results
        mod_path = imp.module.replace(".", "/")

    # --- Resolve ---
    if imp.type == "import":
        # `import pkg.mod` -> resolve to pkg/mod.py or pkg/mod/__init__.py
        target = _try_resolve_module_path(mod_path, repo_root)
        if target:
            results.append(ResolvedImport(
                target_file=target, symbols=symbol_names,
                kind="internal", raw=raw, module_name=imp.module,
            ))
        else:
            results.append(ResolvedImport(
                target_file=None, symbols=symbol_names,
                kind="external", raw=raw, module_name=imp.module,
            ))
        return results

    # `from X import Y, Z` — Y could be a submodule of X OR a symbol within X
    # First, try resolving the base module itself
    base_target = _try_resolve_module_path(mod_path, repo_root)

    # Then try each imported name as a potential submodule
    for name_info in imp.names:
        name = name_info["name"]
        sub_raw = raw  # use the full raw string for all

        if name == "*":
            # `from X import *` — just link to the base module
            if base_target:
                results.append(ResolvedImport(
                    target_file=base_target, symbols=["*"],
                    kind="internal", raw=sub_raw, module_name=imp.module,
                ))
            else:
                results.append(ResolvedImport(
                    target_file=None, symbols=["*"],
                    kind="external", raw=sub_raw, module_name=imp.module,
                ))
            continue

        # Try name as a submodule: X/Y.py or X/Y/__init__.py
        sub_path = mod_path + "/" + name if mod_path else name
        sub_target = _try_resolve_module_path(sub_path, repo_root)

        if sub_target:
            # Y is a submodule
            results.append(ResolvedImport(
                target_file=sub_target, symbols=[name],
                kind="internal", raw=sub_raw, module_name=imp.module,
            ))
        elif base_target:
            # Y is a symbol within the base module
            results.append(ResolvedImport(
                target_file=base_target, symbols=[name],
                kind="internal", raw=sub_raw, module_name=imp.module,
            ))
        else:
            # Neither resolved — external dependency
            full_module = imp.module or ("." * imp.level)
            results.append(ResolvedImport(
                target_file=None, symbols=[name],
                kind="external", raw=sub_raw, module_name=full_module,
            ))

    return results


# ---------------------------------------------------------------------------
# Collect repo data
# ---------------------------------------------------------------------------

def collect_repo_data(repo_root: str) -> tuple[str, str, list[FileInfo], set[str]]:
    """
    Walk the repo, parse Python files, resolve imports.

    Returns: (repo_id, repo_name, files, all_dirs)
    """
    repo_root = os.path.abspath(repo_root)
    repo_id = repo_root.replace("\\", "/")
    repo_name = os.path.basename(repo_root.rstrip("/\\"))

    files: list[FileInfo] = []
    all_dirs: set[str] = set()
    count = 0

    for path in iter_files(repo_root):
        rel_path = os.path.relpath(path, repo_root).replace("\\", "/")
        rel_dir = os.path.dirname(rel_path) or "."
        all_dirs.add(rel_dir)

        lang = lang_for_path(path)

        if path.endswith((".py", ".pyi")):
            try:
                symbols, imports, file_hash, line_count, size_bytes = parse_python(path, repo_root)
            except SyntaxError as e:
                log.warning("Skipping %s: syntax error: %s", rel_path, e)
                # Still create a File node with no symbols
                try:
                    size_bytes = os.path.getsize(path)
                    with open(path, "r", errors="replace") as f:
                        line_count = sum(1 for _ in f)
                except OSError:
                    size_bytes, line_count = 0, 0
                files.append(FileInfo(
                    rel_path=rel_path, rel_dir=rel_dir, lang=lang,
                    file_hash="", line_count=line_count, size_bytes=size_bytes,
                ))
                count += 1
                continue
            except OSError as e:
                log.warning("Skipping %s: %s", rel_path, e)
                continue

            # Resolve imports
            resolved: list[ResolvedImport] = []
            for imp in imports:
                resolved.extend(resolve_import(imp, rel_path, repo_root))

            files.append(FileInfo(
                rel_path=rel_path, rel_dir=rel_dir, lang=lang,
                file_hash=file_hash, line_count=line_count, size_bytes=size_bytes,
                symbols=symbols, imports=imports, resolved_imports=resolved,
            ))
        else:
            # Non-Python: index as File node with metadata only
            try:
                size_bytes = os.path.getsize(path)
                with open(path, "r", errors="replace") as f:
                    line_count = sum(1 for _ in f)
            except OSError:
                size_bytes, line_count = 0, 0

            file_hash = hashlib.sha256(open(path, "rb").read()).hexdigest() if size_bytes else ""
            files.append(FileInfo(
                rel_path=rel_path, rel_dir=rel_dir, lang=lang,
                file_hash=file_hash, line_count=line_count, size_bytes=size_bytes,
            ))

        count += 1
        if count % 50 == 0:
            log.info("Scanned %d files...", count)

    log.info("Scanned %d files total, %d Python files with symbols",
             count, sum(1 for f in files if f.symbols))

    return repo_id, repo_name, files, all_dirs


# ---------------------------------------------------------------------------
# Neo4j graph building
# ---------------------------------------------------------------------------

def _clear_repo(tx, repo_id: str):
    """Delete all existing data for this repo to ensure a clean slate."""
    tx.run("MATCH (r:Repo {id:$repo_id})-[*]->(n) DETACH DELETE n", repo_id=repo_id)
    tx.run("MATCH (r:Repo {id:$repo_id}) DETACH DELETE r", repo_id=repo_id)
    tx.run("MATCH (e:ExternalDep) WHERE NOT ()-[]->(e) DELETE e")
    tx.run("MATCH (s:Schema) DELETE s")


def _ensure_constraints(tx):
    tx.run("CREATE CONSTRAINT repo_id IF NOT EXISTS FOR (r:Repo) REQUIRE r.id IS UNIQUE")
    tx.run("CREATE CONSTRAINT dir_path IF NOT EXISTS FOR (d:Dir) REQUIRE d.path IS UNIQUE")
    tx.run("CREATE CONSTRAINT file_path IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE")
    tx.run("CREATE CONSTRAINT sym_fqn IF NOT EXISTS FOR (s:Symbol) REQUIRE s.fqn IS UNIQUE")
    tx.run("CREATE CONSTRAINT ext_dep_name IF NOT EXISTS FOR (e:ExternalDep) REQUIRE e.name IS UNIQUE")


def _create_schema_node(tx, repo_name: str):
    tx.run("""
    CREATE (s:Schema {
        repo: $repo_name,
        node_types: ['Repo', 'Dir', 'File', 'Symbol', 'ExternalDep'],
        relationship_types: [
            'HAS_DIR: Repo->Dir or Dir->Dir (nested directory hierarchy)',
            'CONTAINS: Dir->File (file inside directory)',
            'DECLARES: File->Symbol (file defines a symbol)',
            'HAS_METHOD: Symbol(class)->Symbol(method)',
            'EXTENDS: Symbol(child class)->Symbol(parent class)',
            'IMPORTS: File->File (one file imports from another, has symbols property)',
            'IMPORTS_SYMBOL: File->Symbol (file imports a specific symbol)',
            'DEPENDS_ON: File->ExternalDep (file uses an external/third-party package)'
        ],
        symbol_kinds: ['class', 'function', 'method', 'constant'],
        description: 'Knowledge graph of Python repository. Query Symbol nodes for code structure, IMPORTS/DEPENDS_ON for dependencies, HAS_METHOD/EXTENDS for class hierarchies.'
    })
    """, repo_name=repo_name)


def _upsert_repo_and_dirs(tx, repo_id: str, repo_name: str, all_dirs: set[str], repo_root: str):
    """Create Repo node and nested Dir hierarchy."""
    tx.run("""
    MERGE (r:Repo {id:$repo_id})
    SET r.name = $repo_name, r.root_path = $root_path
    """, repo_id=repo_id, repo_name=repo_name, root_path=repo_root)

    # Build nested directory tree
    # For each dir like "src/requests/adapters", create:
    #   Dir("src"), Dir("src/requests"), Dir("src/requests/adapters")
    # with HAS_DIR edges between parent->child
    all_dir_paths = set()
    for d in all_dirs:
        if d == ".":
            all_dir_paths.add(".")
            continue
        parts = d.split("/")
        for i in range(len(parts)):
            all_dir_paths.add("/".join(parts[: i + 1]))

    # Check which dirs are Python packages (have __init__.py)
    dir_rows = []
    for d in sorted(all_dir_paths):
        is_package = False
        if d != ".":
            init_path = os.path.join(repo_root, d, "__init__.py")
            is_package = os.path.isfile(init_path)
        dir_rows.append({"path": d, "is_package": is_package})

    # Create all Dir nodes
    tx.run("""
    UNWIND $dirs AS row
    MERGE (d:Dir {path: row.path})
    SET d.is_package = row.is_package
    """, dirs=dir_rows)

    # Link top-level dirs to Repo, and nested dirs to their parent
    for d in sorted(all_dir_paths):
        if d == ".":
            # Root dir links to Repo
            tx.run("""
            MATCH (r:Repo {id:$repo_id}), (d:Dir {path:'.'})
            MERGE (r)-[:HAS_DIR]->(d)
            """, repo_id=repo_id)
        else:
            parent = os.path.dirname(d)
            parent = parent if parent else "."
            tx.run("""
            MATCH (parent:Dir {path:$parent}), (child:Dir {path:$child})
            MERGE (parent)-[:HAS_DIR]->(child)
            """, parent=parent, child=d)


def _upsert_files(tx, file_rows: list[dict]):
    """Create File nodes and link to their parent Dir."""
    tx.run("""
    UNWIND $files AS row
    MERGE (f:File {path: row.path})
    SET f.lang = row.lang,
        f.hash = row.hash,
        f.line_count = row.line_count,
        f.size_bytes = row.size_bytes
    WITH f, row
    MATCH (d:Dir {path: row.dir})
    MERGE (d)-[:CONTAINS]->(f)
    """, files=file_rows)


def _upsert_symbols(tx, file_path: str, symbols: list[SymbolInfo]):
    """Create Symbol nodes, DECLARES edges, and HAS_METHOD / EXTENDS edges."""
    if not symbols:
        return

    sym_rows = []
    for s in symbols:
        sym_rows.append({
            "fqn": s.fqn(file_path),
            "name": s.name,
            "kind": s.kind,
            "lineno": s.lineno,
            "parent_class": s.parent_class,
            "params": s.params,
            "return_annotation": s.return_annotation or "",
            "decorators": s.decorators,
            "docstring": (s.docstring[:500] if s.docstring else ""),
            "bases": s.bases,
        })

    # Create symbols and DECLARES edges
    tx.run("""
    UNWIND $syms AS s
    MATCH (f:File {path: $file_path})
    MERGE (sym:Symbol {fqn: s.fqn})
    SET sym.name = s.name,
        sym.kind = s.kind,
        sym.lineno = s.lineno,
        sym.params = s.params,
        sym.return_annotation = s.return_annotation,
        sym.decorators = s.decorators,
        sym.docstring = s.docstring,
        sym.bases = s.bases
    MERGE (f)-[:DECLARES]->(sym)
    """, file_path=file_path, syms=sym_rows)

    # HAS_METHOD: link methods to their parent class
    methods_with_parent = [s for s in sym_rows if s["parent_class"] and s["kind"] == "method"]
    if methods_with_parent:
        tx.run("""
        UNWIND $methods AS m
        MATCH (cls:Symbol {fqn: $file_path + ':' + m.parent_class})
        MATCH (meth:Symbol {fqn: m.fqn})
        MERGE (cls)-[:HAS_METHOD]->(meth)
        """, file_path=file_path, methods=methods_with_parent)

    # EXTENDS: link classes to their base classes (best-effort within same file)
    classes_with_bases = [s for s in sym_rows if s["kind"] == "class" and s["bases"]]
    for cls_row in classes_with_bases:
        for base_name in cls_row["bases"]:
            # Try to find the base class as a symbol (could be in same file or another)
            # Strip any module prefix (e.g. "base.BaseClass" -> "BaseClass")
            simple_base = base_name.split(".")[-1] if "." in base_name else base_name
            tx.run("""
            MATCH (child:Symbol {fqn: $child_fqn})
            OPTIONAL MATCH (parent:Symbol)
            WHERE parent.name = $base_name AND parent.kind = 'class'
            WITH child, parent
            WHERE parent IS NOT NULL
            MERGE (child)-[:EXTENDS]->(parent)
            """, child_fqn=cls_row["fqn"], base_name=simple_base)


def _upsert_imports(tx, file_path: str, resolved_imports: list[ResolvedImport]):
    """Create IMPORTS (File->File), IMPORTS_SYMBOL, and DEPENDS_ON edges."""
    if not resolved_imports:
        return

    # Group by target file for internal imports
    internal_by_target: dict[str, list[str]] = {}
    external_modules: set[str] = set()

    for ri in resolved_imports:
        if ri.kind == "internal" and ri.target_file:
            if ri.target_file not in internal_by_target:
                internal_by_target[ri.target_file] = []
            internal_by_target[ri.target_file].extend(ri.symbols)
        elif ri.kind == "external" and ri.module_name:
            # Use top-level package name for external deps
            top_level = ri.module_name.split(".")[0] if ri.module_name else None
            if top_level and top_level not in ("", "."):
                external_modules.add(top_level)

    # IMPORTS: File -> File with imported symbol names as property
    for target, symbols in internal_by_target.items():
        unique_symbols = sorted(set(symbols))
        tx.run("""
        MATCH (src:File {path: $src}), (dst:File {path: $dst})
        MERGE (src)-[r:IMPORTS]->(dst)
        SET r.symbols = $symbols
        """, src=file_path, dst=target, symbols=unique_symbols)

    # IMPORTS_SYMBOL: File -> Symbol (when an imported name matches a declared symbol)
    for target, symbols in internal_by_target.items():
        for sym_name in set(symbols):
            if sym_name == "*":
                continue
            # Try to match to a symbol declared in the target file
            tx.run("""
            MATCH (src:File {path: $src})
            MATCH (dst:File {path: $dst})-[:DECLARES]->(sym:Symbol)
            WHERE sym.name = $sym_name
            MERGE (src)-[:IMPORTS_SYMBOL]->(sym)
            """, src=file_path, dst=target, sym_name=sym_name)

    # DEPENDS_ON: File -> ExternalDep
    if external_modules:
        tx.run("""
        UNWIND $mods AS mod_name
        MERGE (e:ExternalDep {name: mod_name})
        WITH e, mod_name
        MATCH (f:File {path: $file_path})
        MERGE (f)-[:DEPENDS_ON]->(e)
        """, file_path=file_path, mods=sorted(external_modules))


def upload_to_neo4j(
    repo_id: str,
    repo_name: str,
    repo_root: str,
    files: list[FileInfo],
    all_dirs: set[str],
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_pass: str,
):
    """Upload all collected data to Neo4j."""
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))

    with driver.session() as session:
        log.info("Clearing existing data for repo...")
        session.execute_write(_clear_repo, repo_id)

        log.info("Creating constraints...")
        session.execute_write(_ensure_constraints)

        log.info("Creating schema node...")
        session.execute_write(_create_schema_node, repo_name)

        log.info("Creating repo and directory hierarchy...")
        session.execute_write(_upsert_repo_and_dirs, repo_id, repo_name, all_dirs, repo_root)

        # Create file nodes
        file_rows = [{
            "path": f.rel_path,
            "dir": f.rel_dir,
            "lang": f.lang,
            "hash": f.file_hash,
            "line_count": f.line_count,
            "size_bytes": f.size_bytes,
        } for f in files]

        log.info("Creating %d file nodes...", len(file_rows))
        # Batch file creation in chunks of 500
        for i in range(0, len(file_rows), 500):
            session.execute_write(_upsert_files, file_rows[i:i + 500])

        # Create symbols and imports per file
        python_files = [f for f in files if f.symbols or f.resolved_imports]
        for idx, fi in enumerate(python_files):
            if fi.symbols:
                session.execute_write(_upsert_symbols, fi.rel_path, fi.symbols)
            if fi.resolved_imports:
                session.execute_write(_upsert_imports, fi.rel_path, fi.resolved_imports)
            if (idx + 1) % 20 == 0:
                log.info("Processed symbols/imports for %d/%d Python files...",
                         idx + 1, len(python_files))

    driver.close()
    log.info("Done! Graph uploaded to Neo4j.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_graph(repo_root: str, neo4j_uri: str, neo4j_user: str, neo4j_pass: str):
    """Main pipeline: collect repo data and upload to Neo4j."""
    repo_id, repo_name, files, all_dirs = collect_repo_data(repo_root)

    # Stats
    py_files = [f for f in files if f.lang == "python"]
    total_symbols = sum(len(f.symbols) for f in py_files)
    internal_imports = sum(
        1 for f in py_files for ri in f.resolved_imports if ri.kind == "internal"
    )
    external_imports = sum(
        1 for f in py_files for ri in f.resolved_imports if ri.kind == "external"
    )
    log.info(
        "Repo: %s | Files: %d (%d Python) | Symbols: %d | "
        "Internal imports: %d | External imports: %d",
        repo_name, len(files), len(py_files), total_symbols,
        internal_imports, external_imports,
    )

    upload_to_neo4j(repo_id, repo_name, os.path.abspath(repo_root),
                    files, all_dirs, neo4j_uri, neo4j_user, neo4j_pass)


def main():
    parser = argparse.ArgumentParser(
        description="Index a Python repository into a Neo4j knowledge graph"
    )
    parser.add_argument("repo_root", help="Path to the repository root directory")
    parser.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI"),
                        help="Neo4j connection URI (default: from NEO4J_URI env var)")
    parser.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"),
                        help="Neo4j username (default: neo4j)")
    parser.add_argument("--neo4j-pass", default=os.environ.get("NEO4J_PASSWORD"),
                        help="Neo4j password (default: from NEO4J_PASSWORD env var)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.neo4j_uri or not args.neo4j_pass:
        log.error("NEO4J_URI and NEO4J_PASSWORD must be set (via env vars or --neo4j-uri/--neo4j-pass)")
        sys.exit(1)

    if not os.path.isdir(args.repo_root):
        log.error("Repository root does not exist: %s", args.repo_root)
        sys.exit(1)

    build_graph(args.repo_root, args.neo4j_uri, args.neo4j_user, args.neo4j_pass)


if __name__ == "__main__":
    main()
