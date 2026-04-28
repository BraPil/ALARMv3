"""Source file parsing, dependency graph construction, and complexity metrics.

The LLM (synthesis.py) NEVER sees raw source files — it queries the
populated tables in analysis.db. This module builds those tables
deterministically using tree-sitter (where available) or regex fallback.

tree-sitter parsers are optional dependencies. Each is loaded with a
try/except ImportError so missing grammars degrade gracefully rather than
blocking startup. VB.NET has no reliable PyPI grammar — it uses regex.
"""

import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from .index import init_analysis_db
from .session import Session


class Analyzer:
    """Parses eligible source files and writes to analysis.db."""

    def __init__(self, session: Session):
        self._session = session
        self._db_path = session.artifact_dir / "analysis.db"
        init_analysis_db(self._db_path)
        self._parsers: dict[str, object] = {}
        self._init_parsers()

    def run(self, pool: ThreadPoolExecutor, job_id: str) -> dict:
        """Claim and analyze all queued files. Returns summary stats."""
        items = []
        while True:
            item = self._session.claim_work("analysis")
            if not item:
                break
            items.append(item)

        stats = {"files_analyzed": 0, "files_failed": 0, "symbols_extracted": 0}
        futures = {pool.submit(self._analyze_file, item): item for item in items}
        for future in as_completed(futures):
            try:
                result = future.result()
                stats["files_analyzed"] += 1
                stats["symbols_extracted"] += result.get("symbols", 0)
            except Exception:
                stats["files_failed"] += 1

        return stats

    # ── Parser initialization ──────────────────────────────────────────────

    def _init_parsers(self) -> None:
        """Load tree-sitter parsers. Each failure is silent — regex handles the gap."""
        from tree_sitter import Language, Parser

        _loads = [
            ("python",     "tree_sitter_python",     "language"),
            ("javascript", "tree_sitter_javascript",  "language"),
            ("java",       "tree_sitter_java",        "language"),
            ("cpp",        "tree_sitter_cpp",         "language"),
            ("csharp",     "tree_sitter_c_sharp",     "language"),
        ]
        for lang, module_name, fn_name in _loads:
            try:
                mod = __import__(module_name)
                lang_obj = getattr(mod, fn_name)()
                self._parsers[lang] = Parser(Language(lang_obj))
            except (ImportError, AttributeError):
                pass

        # TypeScript has two functions: language_typescript() and language_tsx()
        try:
            import tree_sitter_typescript as tsts
            from tree_sitter import Language, Parser
            self._parsers["typescript"] = Parser(Language(tsts.language_typescript()))
        except (ImportError, AttributeError):
            pass

        # VB.NET: tree-sitter-vbnet is not on PyPI — handled by regex fallback below
        try:
            import tree_sitter_vbnet as tsvb
            from tree_sitter import Language, Parser
            self._parsers["vbnet"] = Parser(Language(tsvb.language()))
        except (ImportError, AttributeError):
            pass  # regex fallback in _extract_vbnet_symbols

    # ── Per-file analysis ──────────────────────────────────────────────────

    def _analyze_file(self, work_item: dict) -> dict:
        file_path = Path(work_item["file_path"])
        item_id = work_item["id"]

        try:
            language = self._get_language(file_path)
            if not language:
                self._session.complete_work(item_id)
                return {"symbols": 0}

            try:
                content = file_path.read_text(errors="replace")
            except (PermissionError, OSError) as e:
                self._session.fail_work(item_id, str(e))
                return {"symbols": 0}

            # All downstream tables key on manifest.relative_path. Convert the
            # absolute work-queue path to source-root-relative before writing,
            # so symbol/complexity_metric/dependency_edge join cleanly with the
            # paths emitted by language_researcher (which are already relative).
            rel_path = self._to_relative(file_path)

            symbol_count = 0
            parser = self._parsers.get(language)
            if parser:
                symbol_count = self._parse_with_tree_sitter(parser, language, content, file_path, rel_path)
            else:
                symbol_count = self._parse_with_fallback(language, content, file_path, rel_path)

            self._compute_complexity(language, content, rel_path)
            self._extract_dependencies(language, content, rel_path)

            self._session.complete_work(item_id, {"symbols": symbol_count})
            return {"symbols": symbol_count}

        except Exception as e:
            self._session.fail_work(item_id, str(e))
            raise

    def _to_relative(self, abs_path: Path) -> str:
        """Return path relative to session.source_path; fall back to str(abs_path)."""
        source_root = self._session.source_path
        if source_root is None:
            return str(abs_path)
        try:
            return str(abs_path.relative_to(source_root))
        except ValueError:
            return str(abs_path)

    def _get_language(self, file_path: Path) -> Optional[str]:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            row = conn.execute(
                "SELECT language FROM manifest WHERE file_path=? AND session_id=?",
                (str(file_path), self._session.session_id),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    # ── Tree-sitter parsing ────────────────────────────────────────────────

    def _parse_with_tree_sitter(self, parser, language: str, content: str, abs_path: Path, rel_path: str) -> int:
        tree = parser.parse(content.encode())
        extractor = _EXTRACTORS.get(language, _generic_extractor)
        symbols = extractor(tree.root_node, content, rel_path, self._session.session_id)
        self._write_symbols(symbols)
        return len(symbols)

    # ── Regex / heuristic fallback ─────────────────────────────────────────

    def _parse_with_fallback(self, language: str, content: str, abs_path: Path, rel_path: str) -> int:
        if language == "vbnet":
            symbols = _extract_vbnet_symbols(content, rel_path, self._session.session_id)
        else:
            symbols = []
        self._write_symbols(symbols)
        return len(symbols)

    # ── Complexity metrics ─────────────────────────────────────────────────

    def _compute_complexity(self, language: str, content: str, rel_path: str) -> None:
        lines = content.splitlines()
        loc = len([l for l in lines if l.strip() and not l.strip().startswith(("#", "//", "/*", "*", "'''", '"""'))])

        metrics = [
            ("loc", float(loc)),
            ("total_lines", float(len(lines))),
        ]
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            for name, value in metrics:
                conn.execute(
                    "INSERT OR REPLACE INTO complexity_metric"
                    "(session_id, file_path, metric_name, metric_value, computed_at) "
                    "VALUES (?,?,?,?,?)",
                    (self._session.session_id, rel_path, name, value, time.time()),
                )
            conn.commit()
        finally:
            conn.close()

    # ── Dependency extraction ──────────────────────────────────────────────

    def _extract_dependencies(self, language: str, content: str, rel_path: str) -> None:
        deps: list[tuple[str, str, int]] = []  # (target, dep_type, line_no)

        extractor_fn = _DEP_EXTRACTORS.get(language)
        if extractor_fn:
            deps = extractor_fn(content)

        if not deps:
            return

        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            for target, dep_type, line_no in deps:
                conn.execute(
                    "INSERT INTO dependency_edge"
                    "(session_id, source_file, target_module, dep_type, line_number) "
                    "VALUES (?,?,?,?,?)",
                    (self._session.session_id, rel_path, target, dep_type, line_no),
                )
            conn.commit()
        finally:
            conn.close()

    # ── Symbol writer ──────────────────────────────────────────────────────

    def _write_symbols(self, symbols: list[dict]) -> None:
        if not symbols:
            return
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            for s in symbols:
                conn.execute(
                    "INSERT INTO symbol"
                    "(session_id, file_path, name, symbol_type, start_line, end_line, signature) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        s["session_id"],
                        s["file_path"],
                        s["name"],
                        s["symbol_type"],
                        s.get("start_line"),
                        s.get("end_line"),
                        s.get("signature"),
                    ),
                )
            conn.commit()
        finally:
            conn.close()


# ── Tree-sitter extractors ─────────────────────────────────────────────────
# Each returns a list of symbol dicts with keys:
#   session_id, file_path, name, symbol_type, start_line, end_line, signature

def _python_extractor(root, content: str, file_path: str, session_id: str) -> list[dict]:
    symbols = []

    def walk(node):
        if node.type in ("function_definition", "async_function_definition"):
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append({
                    "session_id": session_id, "file_path": file_path,
                    "name": name_node.text.decode(),
                    "symbol_type": "function",
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                })
        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append({
                    "session_id": session_id, "file_path": file_path,
                    "name": name_node.text.decode(),
                    "symbol_type": "class",
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                })
        for child in node.children:
            walk(child)

    walk(root)
    return symbols


def _cpp_extractor(root, content: str, file_path: str, session_id: str) -> list[dict]:
    symbols = []

    def walk(node):
        if node.type == "function_definition":
            # Look for declarator → function_declarator → identifier
            decl = node.child_by_field_name("declarator")
            if decl:
                name_node = _find_identifier(decl)
                if name_node:
                    symbols.append({
                        "session_id": session_id, "file_path": file_path,
                        "name": name_node.text.decode(errors="replace"),
                        "symbol_type": "function",
                        "start_line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1,
                    })
        elif node.type in ("class_specifier", "struct_specifier"):
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append({
                    "session_id": session_id, "file_path": file_path,
                    "name": name_node.text.decode(errors="replace"),
                    "symbol_type": "class" if node.type == "class_specifier" else "struct",
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                })
        for child in node.children:
            walk(child)

    walk(root)
    return symbols


def _find_identifier(node) -> Optional[object]:
    """Recursively find the first identifier node."""
    if node.type in ("identifier", "qualified_identifier", "field_identifier",
                     "destructor_name", "operator_name"):
        return node
    for child in node.children:
        found = _find_identifier(child)
        if found:
            return found
    return None


def _java_extractor(root, content: str, file_path: str, session_id: str) -> list[dict]:
    symbols = []

    def walk(node):
        if node.type in ("method_declaration", "constructor_declaration"):
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append({
                    "session_id": session_id, "file_path": file_path,
                    "name": name_node.text.decode(),
                    "symbol_type": "function",
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                })
        elif node.type in ("class_declaration", "interface_declaration", "enum_declaration"):
            name_node = node.child_by_field_name("name")
            if name_node:
                sym_type = "class" if "class" in node.type else \
                           "interface" if "interface" in node.type else "enum"
                symbols.append({
                    "session_id": session_id, "file_path": file_path,
                    "name": name_node.text.decode(),
                    "symbol_type": sym_type,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                })
        for child in node.children:
            walk(child)

    walk(root)
    return symbols


def _csharp_extractor(root, content: str, file_path: str, session_id: str) -> list[dict]:
    symbols = []

    def walk(node):
        if node.type == "method_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append({
                    "session_id": session_id, "file_path": file_path,
                    "name": name_node.text.decode(),
                    "symbol_type": "function",
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                })
        elif node.type in ("class_declaration", "interface_declaration",
                           "struct_declaration", "enum_declaration"):
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append({
                    "session_id": session_id, "file_path": file_path,
                    "name": name_node.text.decode(),
                    "symbol_type": node.type.replace("_declaration", ""),
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                })
        for child in node.children:
            walk(child)

    walk(root)
    return symbols


def _generic_extractor(root, content: str, file_path: str, session_id: str) -> list[dict]:
    return []


_EXTRACTORS = {
    "python":     _python_extractor,
    "javascript": _generic_extractor,  # JS symbols via tree-sitter but no custom extractor yet
    "typescript": _generic_extractor,
    "cpp":        _cpp_extractor,
    "java":       _java_extractor,
    "csharp":     _csharp_extractor,
}


# ── VB.NET regex fallback ──────────────────────────────────────────────────

_VB_PATTERNS = [
    (re.compile(
        r"^\s*(?:Public|Private|Protected|Friend|Static)?\s*"
        r"(?:Shared\s+)?(?:Overrides\s+)?(?:Overridable\s+)?"
        r"(?:Sub|Function)\s+(\w+)",
        re.IGNORECASE | re.MULTILINE,
    ), "function"),
    (re.compile(
        r"^\s*(?:Public|Private|Friend)?\s*(?:MustInherit\s+|NotInheritable\s+)?Class\s+(\w+)",
        re.IGNORECASE | re.MULTILINE,
    ), "class"),
    (re.compile(
        r"^\s*Module\s+(\w+)",
        re.IGNORECASE | re.MULTILINE,
    ), "class"),
    (re.compile(
        r"^\s*(?:Public|Private)?\s*Interface\s+(\w+)",
        re.IGNORECASE | re.MULTILINE,
    ), "interface"),
    (re.compile(
        r"^\s*(?:Public|Private)?\s*Enum\s+(\w+)",
        re.IGNORECASE | re.MULTILINE,
    ), "enum"),
]


def _extract_vbnet_symbols(content: str, file_path: str, session_id: str) -> list[dict]:
    symbols = []
    lines = content.splitlines()
    for i, line in enumerate(lines, 1):
        for pattern, sym_type in _VB_PATTERNS:
            m = pattern.match(line)
            if m:
                symbols.append({
                    "session_id": session_id,
                    "file_path": file_path,
                    "name": m.group(1),
                    "symbol_type": sym_type,
                    "start_line": i,
                    "end_line": i,
                })
                break
    return symbols


# ── Dependency extractors ──────────────────────────────────────────────────

def _python_deps(content: str) -> list[tuple[str, str, int]]:
    deps = []
    for i, line in enumerate(content.splitlines(), 1):
        m = re.match(r"^\s*(?:import|from)\s+([\w\.]+)", line)
        if m:
            deps.append((m.group(1), "import", i))
    return deps


def _cpp_deps(content: str) -> list[tuple[str, str, int]]:
    deps = []
    for i, line in enumerate(content.splitlines(), 1):
        m = re.match(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', line)
        if m:
            deps.append((m.group(1), "include", i))
    return deps


def _vbnet_deps(content: str) -> list[tuple[str, str, int]]:
    deps = []
    for i, line in enumerate(content.splitlines(), 1):
        m = re.match(r"^\s*Imports\s+([\w\.]+)", line, re.IGNORECASE)
        if m:
            deps.append((m.group(1), "imports", i))
    return deps


def _js_deps(content: str) -> list[tuple[str, str, int]]:
    deps = []
    pat = re.compile(r"""(?:import|require)\s*.*?['"]([^'"]+)['"]""")
    for i, line in enumerate(content.splitlines(), 1):
        m = pat.search(line)
        if m:
            deps.append((m.group(1), "import", i))
    return deps


def _java_deps(content: str) -> list[tuple[str, str, int]]:
    deps = []
    for i, line in enumerate(content.splitlines(), 1):
        m = re.match(r"^\s*import\s+([\w\.]+)\s*;", line)
        if m:
            deps.append((m.group(1), "import", i))
    return deps


def _csharp_deps(content: str) -> list[tuple[str, str, int]]:
    deps = []
    for i, line in enumerate(content.splitlines(), 1):
        m = re.match(r"^\s*using\s+([\w\.]+)\s*;", line)
        if m:
            deps.append((m.group(1), "using", i))
    return deps


_DEP_EXTRACTORS = {
    "python":     _python_deps,
    "cpp":        _cpp_deps,
    "vbnet":      _vbnet_deps,
    "javascript": _js_deps,
    "typescript": _js_deps,
    "java":       _java_deps,
    "csharp":     _csharp_deps,
}
