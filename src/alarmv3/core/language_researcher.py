"""Phase 7: Runtime language inference for unknown extensions.

Three-tier hybrid approach (AAA board recommendation):
  Tier 1 — detection (existing discovery.py, unchanged)
  Tier 2 — runtime grammar inference: sample unknown files, one Claude call per
            language family, extract heuristic regexes, run over all unknown files,
            write inferred symbols/deps into existing tables
  Tier 3 — validated persistence: if symbol yield clears the plausibility gate,
            cache the grammar in language_grammar table and persist to ProjectMemory

The LLM board rule ("LLM reads semantic graph, not raw files") does NOT apply here
because grammar inference is a meta-task: we feed tiny file samples so the LLM
can describe the syntax, not analyse the architecture. The symbols it produces are
then stored in the existing `symbol` and `dependency_edge` tables so the downstream
synthesis pipeline can treat them like first-class findings.
"""

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

import anthropic

from .memory import ProjectMemory
from .session import Session

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 2048
_MIN_SYMBOL_YIELD = 3        # minimum inferred symbols before persisting grammar
_MAX_SAMPLES = 5             # file samples sent to Claude per language
_MAX_SAMPLE_LINES = 60       # lines per sample file

_RESEARCH_PROMPT = """\
You are a programming language expert. I will show you source code samples from \
an unknown or uncommon programming language identified by file extension "{ext}".

Your job is to produce a JSON grammar descriptor that describes the syntax patterns \
in the samples. The descriptor will be used to extract function names, class names, \
and import statements from MORE files of the same type using Python regex patterns.

Respond with ONLY a valid JSON object in this exact shape:
{{
  "language_name": "human readable name (e.g. AutoLISP, PowerShell, COBOL)",
  "function_patterns": ["list of Python regex patterns that match function/procedure definitions"],
  "class_patterns": ["list of Python regex patterns that match class/struct/module definitions"],
  "import_patterns": ["list of Python regex patterns that match import/require/load statements"],
  "notes": "one sentence about the language family and key syntax quirks"
}}

Rules for the patterns:
- Each pattern must have at least one capture group containing the name
- Patterns are applied line-by-line (re.search per line)
- Prefer case-insensitive patterns for case-insensitive languages
- Include the most common variants (e.g. AutoLISP uses both defun and defun-q)

---
FILE SAMPLES:
{samples}
"""

_PLAUSIBLE_NAME_RE = re.compile(r'^[A-Za-z_][\w\-:./]*$')


class LanguageResearcher:
    """Infers grammar patterns for unknown language files and populates the symbol table."""

    def __init__(self, session: Session):
        self._session = session
        self._db_path = session.artifact_dir / "analysis.db"
        self._client = anthropic.Anthropic()

    # ── Public API ─────────────────────────────────────────────────────────

    def run(
        self,
        max_samples_per_language: int = _MAX_SAMPLES,
        persist_on_success: bool = True,
    ) -> dict:
        """Research all ineligible unknown-language files. Returns summary dict."""
        ext_groups = self._find_unknown_extensions()
        if not ext_groups:
            return {"languages_researched": 0, "total_symbols_inferred": 0, "message": "No unknown language files found."}

        total_symbols = 0
        researched = []
        for ext, file_paths in ext_groups.items():
            sample_paths = file_paths[:max_samples_per_language]
            grammar = self._load_cached_grammar(ext) or self._research_language(ext, sample_paths)
            if not grammar:
                continue

            symbols, deps = self._extract_all(ext, grammar, file_paths)
            self._store_results(ext, symbols, deps)
            self._mark_eligible(ext, file_paths)

            passed = self._validate(symbols)
            if persist_on_success and passed:
                self._persist_grammar(ext, grammar, len(symbols))

            total_symbols += len(symbols)
            researched.append({
                "ext": ext,
                "language": grammar.get("language_name", ext),
                "files": len(file_paths),
                "symbols": len(symbols),
                "deps": len(deps),
                "persisted": persist_on_success and passed,
            })

        return {
            "languages_researched": len(researched),
            "total_symbols_inferred": total_symbols,
            "details": researched,
            "message": (
                f"Researched {len(researched)} unknown language(s), "
                f"inferred {total_symbols} symbols total."
            ),
        }

    def load_cached_grammar(self, ext: str) -> Optional[dict]:
        """Public accessor for cached grammar (used by tests)."""
        return self._load_cached_grammar(ext)

    # ── Tier 2: runtime inference ──────────────────────────────────────────

    def _research_language(self, ext: str, sample_paths: list[Path]) -> Optional[dict]:
        """Call Claude once with file samples; return grammar dict or None."""
        samples_text = self._build_samples_text(sample_paths)
        if not samples_text.strip():
            return None

        prompt = _RESEARCH_PROMPT.format(ext=ext, samples=samples_text)
        try:
            resp = self._client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            grammar = self._parse_grammar(raw)
            if grammar:
                self._cache_grammar(ext, grammar)
            return grammar
        except Exception:
            return None

    def _build_samples_text(self, paths: list[Path]) -> str:
        source = self._session.source_path
        lines = []
        for p in paths:
            full = source / p if not Path(p).is_absolute() else Path(p)
            try:
                content = full.read_text(errors="replace")
                snippet = "\n".join(content.splitlines()[:_MAX_SAMPLE_LINES])
                lines.append(f"=== {p} ===\n{snippet}\n")
            except OSError:
                continue
        return "\n".join(lines)

    def _parse_grammar(self, raw: str) -> Optional[dict]:
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start == -1 or end == 0:
                return None
            return json.loads(raw[start:end])
        except (json.JSONDecodeError, ValueError):
            return None

    # ── Tier 2: extraction ─────────────────────────────────────────────────

    def _extract_all(
        self,
        ext: str,
        grammar: dict,
        file_paths: list[Path],
    ) -> tuple[list[dict], list[dict]]:
        source = self._session.source_path
        sid = self._session.session_id
        all_symbols: list[dict] = []
        all_deps: list[dict] = []

        func_pats = self._compile(grammar.get("function_patterns", []))
        class_pats = self._compile(grammar.get("class_patterns", []))
        import_pats = self._compile(grammar.get("import_patterns", []))

        for rel_path in file_paths:
            full = source / rel_path if not Path(rel_path).is_absolute() else Path(rel_path)
            try:
                lines = full.read_text(errors="replace").splitlines()
            except OSError:
                continue

            for lineno, line in enumerate(lines, 1):
                for pat, sym_type in [*((p, "inferred_function") for p in func_pats),
                                       *((p, "inferred_class") for p in class_pats)]:
                    m = pat.search(line)
                    if m:
                        try:
                            name = m.group(1)
                        except IndexError:
                            continue
                        if name and _PLAUSIBLE_NAME_RE.match(name):
                            all_symbols.append({
                                "session_id": sid,
                                "file_path": str(rel_path),
                                "name": name,
                                "symbol_type": sym_type,
                                "start_line": lineno,
                                "end_line": lineno,
                                "signature": line.strip()[:200],
                                "is_public": 1,
                            })

                for pat in import_pats:
                    m = pat.search(line)
                    if m:
                        try:
                            target = m.group(1)
                        except IndexError:
                            continue
                        if target:
                            all_deps.append({
                                "session_id": sid,
                                "source_file": str(rel_path),
                                "target_module": target.strip()[:200],
                                "dep_type": "inferred_import",
                                "line_number": lineno,
                                "is_resolved": 0,
                            })

        return all_symbols, all_deps

    @staticmethod
    def _compile(patterns: list[str]) -> list[re.Pattern]:
        compiled = []
        for p in patterns:
            try:
                compiled.append(re.compile(p, re.IGNORECASE))
            except re.error:
                pass
        return compiled

    # ── Tier 3: validation and persistence ────────────────────────────────

    def _validate(self, symbols: list[dict]) -> bool:
        if len(symbols) < _MIN_SYMBOL_YIELD:
            return False
        plausible = sum(1 for s in symbols if _PLAUSIBLE_NAME_RE.match(s["name"]))
        return plausible >= _MIN_SYMBOL_YIELD

    def _persist_grammar(self, ext: str, grammar: dict, symbol_count: int) -> None:
        lang = grammar.get("language_name", ext)
        memory = ProjectMemory(self._session.alarm_dir)
        memory.record(
            category="pattern",
            key=f"language/{ext.lstrip('.')}",
            content=(
                f"Grammar learned for {lang} ({ext}). "
                f"Produced {symbol_count} symbols. Notes: {grammar.get('notes', '')} "
                f"Patterns: function={grammar.get('function_patterns', [])}, "
                f"class={grammar.get('class_patterns', [])}, "
                f"import={grammar.get('import_patterns', [])}"
            ),
            session_id=self._session.session_id,
        )

    # ── SQLite helpers ─────────────────────────────────────────────────────

    def _find_unknown_extensions(self) -> dict[str, list[Path]]:
        """Return {ext: [relative_paths]} for ineligible, language=None files."""
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT file_path, relative_path FROM manifest "
                "WHERE session_id=? AND is_eligible=0 AND language IS NULL",
                (self._session.session_id,),
            ).fetchall()
        finally:
            conn.close()

        groups: dict[str, list[Path]] = {}
        for row in rows:
            ext = Path(row["relative_path"]).suffix.lower()
            if ext:
                groups.setdefault(ext, []).append(Path(row["relative_path"]))
        return groups

    def _store_results(self, ext: str, symbols: list[dict], deps: list[dict]) -> None:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            for s in symbols:
                conn.execute(
                    "INSERT OR IGNORE INTO symbol"
                    "(session_id, file_path, name, symbol_type, start_line, end_line, signature, is_public)"
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (s["session_id"], s["file_path"], s["name"], s["symbol_type"],
                     s["start_line"], s["end_line"], s["signature"], s["is_public"]),
                )
            for d in deps:
                conn.execute(
                    "INSERT INTO dependency_edge"
                    "(session_id, source_file, target_module, dep_type, line_number, is_resolved)"
                    "VALUES (?,?,?,?,?,?)",
                    (d["session_id"], d["source_file"], d["target_module"],
                     d["dep_type"], d["line_number"], d["is_resolved"]),
                )
            conn.commit()
        finally:
            conn.close()

    def _mark_eligible(self, ext: str, file_paths: list[Path]) -> None:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            lang_name = f"inferred_{ext.lstrip('.')}"
            for rel_path in file_paths:
                conn.execute(
                    "UPDATE manifest SET is_eligible=1, language=? "
                    "WHERE session_id=? AND relative_path=?",
                    (lang_name, self._session.session_id, str(rel_path)),
                )
            conn.commit()
        finally:
            conn.close()

    def _load_cached_grammar(self, ext: str) -> Optional[dict]:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT grammar_json FROM language_grammar "
                "WHERE session_id=? AND file_ext=?",
                (self._session.session_id, ext),
            ).fetchone()
        finally:
            conn.close()
        if row:
            try:
                return json.loads(row["grammar_json"])
            except (json.JSONDecodeError, TypeError):
                return None
        # Fall back to ProjectMemory for grammars persisted in prior sessions
        return self._load_from_memory(ext)

    def _load_from_memory(self, ext: str) -> Optional[dict]:
        try:
            memory = ProjectMemory(self._session.alarm_dir)
            entries = memory.list(category="pattern")
            key = f"language/{ext.lstrip('.')}"
            for e in entries:
                if e["key"] == key:
                    # Reconstruct a minimal grammar dict from the stored content
                    content = e["content"]
                    pats: dict[str, list] = {}
                    for field in ("function_patterns", "class_patterns", "import_patterns"):
                        m = re.search(rf"{field}=(\[.*?\])", content)
                        if m:
                            try:
                                pats[field] = json.loads(m.group(1))
                            except json.JSONDecodeError:
                                pats[field] = []
                    if any(pats.values()):
                        return {
                            "language_name": ext,
                            **pats,
                            "notes": "(restored from project memory)",
                        }
        except Exception:
            pass
        return None

    def _cache_grammar(self, ext: str, grammar: dict) -> None:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute(
                "INSERT INTO language_grammar(session_id, file_ext, language_name, grammar_json, created_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(session_id, file_ext) DO UPDATE SET "
                "grammar_json=excluded.grammar_json, language_name=excluded.language_name",
                (
                    self._session.session_id,
                    ext,
                    grammar.get("language_name", ext),
                    json.dumps(grammar),
                    time.time(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
