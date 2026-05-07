"""Tree-sitter-based multi-language symbol parser."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from tree_sitter_language_pack import get_parser

from .db import Symbol

LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cs": "c_sharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".md": "markdown",
    ".db": "sqlite",
    # Web
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "scss",
    ".less": "less",
    ".vue": "vue",
    ".svelte": "svelte",
    # Systems
    ".lua": "lua",
    ".zig": "zig",
    ".dart": "dart",
    # Shell
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".fish": "fish",
    ".ps1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    # JVM / functional
    ".scala": "scala",
    ".groovy": "groovy",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".cljc": "clojure",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".mli": "ocaml",
    # Scripting / data science
    ".pl": "perl",
    ".pm": "perl",
    ".r": "r",
    ".R": "r",
    ".nix": "nix",
    # Data / config / markup
    ".xml": "xml",
    ".plist": "xml",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "proto",
    ".tf": "hcl",
    ".hcl": "hcl",
    ".sql": "sql",
    # Build / infra
    ".dockerfile": "dockerfile",
    ".mk": "make",
    ".make": "make",
}

FILENAME_MAP: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Makefile": "make",
    "makefile": "make",
    "GNUmakefile": "make",
}


def detect_language(file_path: str) -> Optional[str]:
    """Return tree-sitter language name for the file, or None."""
    p = Path(file_path)
    lang = FILENAME_MAP.get(p.name)
    if lang:
        return lang
    return LANGUAGE_MAP.get(p.suffix)


class SymbolParser:
    """Facade that manages per-language parsers and dispatches parse requests."""

    def __init__(self) -> None:
        self._parsers: dict[str, object] = {}

    def _get_parser(self, language: str):
        if language not in self._parsers:
            try:
                self._parsers[language] = get_parser(language)
            except Exception:
                self._parsers[language] = None  # unavailable — skip silently
        return self._parsers[language]

    def parse_file(self, file_path: str, source: bytes | None = None) -> list[Symbol]:
        """Parse a file and return extracted symbols. Pass source to avoid a second read."""
        language = detect_language(file_path)
        if language is None:
            return []

        if language == "sqlite":
            return _parse_sqlite_schema(file_path)

        if source is None:
            source = Path(file_path).read_bytes()
        parser = self._get_parser(language)
        if parser is None:
            return []
        tree = parser.parse(source)

        extractor = SymbolExtractor(source=source, language=language, file_path=file_path)
        return extractor.extract(tree.root_node)


def _parse_sqlite_schema(file_path: str) -> list[Symbol]:
    """Extract tables and views from a SQLite database as symbols."""
    import sqlite3 as _sqlite3
    symbols: list[Symbol] = []
    try:
        conn = _sqlite3.connect(f"file:{file_path}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        ).fetchall()
        conn.close()
    except Exception:
        return []
    for line_no, (obj_type, name, ddl) in enumerate(rows, start=1):
        kind = "table" if obj_type == "table" else "view"
        signature = (ddl or "").split("\n")[0].strip()[:120]
        symbols.append(Symbol(
            name=name,
            kind=kind,
            file_path=file_path,
            start_line=line_no,
            end_line=line_no,
            signature=signature,
            docstring=None,
            parent_name=None,
            parent_id=None,
            language="sqlite",
            checksum="",
        ))
    return symbols


class SymbolExtractor:
    """Walks a tree-sitter AST and extracts Symbol objects."""

    def __init__(self, source: bytes, language: str, file_path: str) -> None:
        self.source = source
        self.language = language
        self.file_path = file_path
        self.lines = source.decode("utf-8", errors="replace").splitlines()

    def extract(self, root_node) -> list[Symbol]:
        symbols: list[Symbol] = []
        self._walk(root_node, symbols, parent_name=None, parent_id=None)
        return symbols

    def _walk(self, node, symbols: list[Symbol], parent_name: Optional[str], parent_id: Optional[int]) -> None:
        sym = self._extract_node(node, parent_name, parent_id)
        if sym is not None:
            symbols.append(sym)
            # Recurse into children with this symbol as parent context
            for child in node.children:
                self._walk(child, symbols, parent_name=sym.name, parent_id=sym.id)
        else:
            # Not a symbol node — recurse with current parent context unchanged
            for child in node.children:
                self._walk(child, symbols, parent_name=parent_name, parent_id=parent_id)

    def _extract_node(self, node, parent_name: Optional[str], parent_id: Optional[int]) -> Optional[Symbol]:
        kind = self._node_kind(node)
        if kind is None:
            return None

        name = self._get_name(node)
        if name is None:
            return None

        start_line = node.start_point[0] + 1  # 1-indexed
        end_line = node.end_point[0] + 1      # 1-indexed

        signature = self._get_signature(node, start_line)
        docstring = self._get_docstring(node)

        return Symbol(
            name=name,
            kind=kind,
            file_path=self.file_path,
            start_line=start_line,
            end_line=end_line,
            signature=signature,
            docstring=docstring,
            parent_name=parent_name,
            parent_id=parent_id,
            language=self.language,
            checksum="",
        )

    def _node_kind(self, node) -> Optional[str]:
        t = node.type
        lang = self.language

        if lang == "python":
            if t == "function_definition":
                return "method" if self._has_class_parent(node) else "function"
            if t == "class_definition":
                return "class"
            if t in ("import_statement", "import_from_statement"):
                return "import"
            if t == "assignment" and node.parent and node.parent.type == "module":
                # module-level assignment → variable
                return "variable"
            if t == "expression_statement" and node.parent and node.parent.type == "module":
                # some tree-sitter versions wrap assignments in expression_statement
                for child in node.children:
                    if child.type == "assignment":
                        return "variable"
                return None

        elif lang in ("javascript", "typescript", "tsx"):
            if t == "function_declaration":
                return "function"
            if t == "variable_declarator":
                # check if value is arrow_function or function_expression
                for child in node.children:
                    if child.type in ("arrow_function", "function_expression"):
                        return "function"
                # plain variable_declarator — parent lexical_declaration handles this
                return None
            if t == "lexical_declaration" and node.parent and node.parent.type in ("program", "module"):
                # only emit "variable" if no child declarator is a function (avoid double-counting)
                for child in node.children:
                    if child.type == "variable_declarator":
                        for grandchild in child.children:
                            if grandchild.type in ("arrow_function", "function_expression"):
                                return None  # let variable_declarator emit "function"
                return "variable"
            if t == "import_declaration":
                return "import"
            if t == "class_declaration":
                return "class"
            if t == "method_definition":
                return "method"

        elif lang == "go":
            if t == "function_declaration":
                return "function"
            if t == "method_declaration":
                return "method"
            if t == "type_declaration":
                return "class"

        elif lang == "rust":
            if t == "function_item":
                return "function"
            if t in ("struct_item", "enum_item", "trait_item", "impl_item"):
                return "class"

        elif lang == "java":
            if t == "method_declaration":
                return "method"
            if t == "class_declaration":
                return "class"

        elif lang == "json":
            if t == "pair":
                return "variable"
            if t == "object":
                return None  # don't create a symbol for the object container itself

        elif lang == "yaml":
            if t in ("block_mapping_pair", "flow_pair"):
                return "variable"

        elif lang == "toml":
            if t == "table":
                return "section"
            if t == "pair":
                return "variable"

        elif lang == "ini":
            if t == "section":
                return "section"
            if t == "setting":
                return "variable"

        elif lang in ("c", "cpp"):
            if t == "function_definition":
                return "function"
            if t == "type_definition":
                return "class"
            if t == "class_specifier":
                return "class"
            if t == "namespace_definition":
                return "class"
            if t == "preproc_include":
                return "import"
            if t == "preproc_def":
                return "variable"

        elif lang == "markdown":
            if t == "section":
                # Only ATX-headed sections become symbols; setext_heading siblings handled below
                for child in node.children:
                    if child.type == "atx_heading":
                        return "section"
                return None
            if t == "setext_heading":
                return "section"

        elif lang in ("css", "scss", "less"):
            if t == "rule_set":
                return "section"
            if t in ("media_statement", "supports_statement", "keyframes_statement"):
                return "section"
            if t == "mixin_statement":
                return "function"

        elif lang == "html":
            if t == "element" and node.parent and node.parent.type == "document":
                return "section"

        elif lang == "lua":
            if t == "function_declaration":
                return "function"

        elif lang == "bash":
            if t == "function_definition":
                return "function"

        elif lang == "r":
            if t == "binary_operator":
                for child in node.children:
                    if child.type == "function_definition":
                        return "function"

        elif lang == "scala":
            if t == "function_definition":
                return "function"
            if t in ("class_definition", "object_definition", "trait_definition"):
                return "class"

        elif lang == "elixir":
            if t == "call":
                for child in node.children:
                    if child.type == "identifier":
                        if child.text in (b"defmodule", b"defprotocol", b"defimpl"):
                            return "class"
                        if child.text in (b"def", b"defp", b"defmacro", b"defmacrop"):
                            return "function"
                    break

        elif lang == "erlang":
            if t == "fun_decl":
                return "function"

        elif lang == "haskell":
            if t in ("function", "bind"):
                return "function"

        elif lang == "ocaml":
            if t == "value_definition":
                return "function"
            if t == "module_definition":
                return "class"

        elif lang == "dart":
            if t == "class_definition":
                return "class"
            if t == "function_signature":
                if node.parent and node.parent.type not in ("class_body", "method_signature"):
                    return "function"
            if t == "method_signature":
                return "method"

        elif lang == "hcl":
            if t == "block":
                return "section"

        elif lang == "proto":
            if t == "message":
                return "class"
            if t == "service":
                return "class"
            if t == "rpc":
                return "function"

        elif lang == "graphql":
            if t == "type_system_definition":
                return "class"

        elif lang == "sql":
            if t == "create_table":
                return "class"
            if t == "create_view":
                return "class"
            if t == "create_index":
                return "variable"
            if t == "create_function":
                return "function"

        elif lang == "xml":
            if t == "element" and node.parent and node.parent.type == "document":
                return "section"

        elif lang in ("svelte", "vue"):
            if t in ("script_element", "style_element", "template_element"):
                return "section"

        elif lang == "powershell":
            if t == "function_statement":
                return "function"

        elif lang == "dockerfile":
            if t == "from_instruction":
                return "import"

        elif lang == "make":
            if t == "rule":
                return "function"
            if t == "variable_assignment":
                return "variable"

        elif lang == "perl":
            if t == "subroutine_declaration_statement":
                return "function"
            if t == "package_statement":
                return "class"

        elif lang == "zig":
            if t == "FnProto":
                return "function"
            if t == "VarDecl":
                return "variable"

        elif lang == "clojure":
            if t == "list_lit":
                for child in node.children:
                    if child.type == "sym_lit":
                        if child.text in (b"defn", b"defn-", b"defmacro"):
                            return "function"
                        if child.text in (b"def", b"defonce"):
                            return "variable"
                        if child.text in (b"ns", b"defprotocol", b"deftype", b"defrecord"):
                            return "class"
                        break  # stop after first sym_lit

        elif lang == "fish":
            if t == "function_definition":
                return "function"

        elif lang == "batch":
            if t == "function_definition":
                return "function"

        return None

    def _has_class_parent(self, node) -> bool:
        """Walk up the parent chain and return True if any ancestor is a class_definition."""
        current = node.parent
        while current is not None:
            if current.type == "class_definition":
                return True
            current = current.parent
        return False

    def _get_name(self, node) -> Optional[str]:
        """Return the text of the first child node with type 'identifier'."""
        t = node.type

        # Imports: use the full first line as the name (up to 80 chars)
        if t in ("import_statement", "import_from_statement", "import_declaration"):
            return node.text.decode("utf-8", errors="replace").split("\n")[0].strip()[:80]

        # Python module-level variable: direct assignment node at module level
        if t == "assignment":
            lhs = node.child_by_field_name("left")
            if lhs is not None:
                return lhs.text.decode("utf-8", errors="replace").strip()
            # fallback: first identifier child
            for child in node.children:
                if child.type == "identifier":
                    return child.text.decode("utf-8", errors="replace")
            return None

        # Python module-level variable: expression_statement → assignment (older tree-sitter)
        if t == "expression_statement":
            for child in node.children:
                if child.type == "assignment":
                    lhs = child.child_by_field_name("left")
                    if lhs is not None:
                        return lhs.text.decode("utf-8", errors="replace").strip()
                    # fallback: first identifier child of assignment
                    for gc in child.children:
                        if gc.type == "identifier":
                            return gc.text.decode("utf-8", errors="replace")
            return None

        # JS/TS: variable_declarator — name is the identifier child
        if t == "variable_declarator":
            for child in node.children:
                if child.type == "identifier":
                    return child.text.decode("utf-8", errors="replace")
            return None

        # JS/TS: lexical_declaration (top-level const/let) — name from first variable_declarator
        if t == "lexical_declaration":
            for child in node.children:
                if child.type == "variable_declarator":
                    for gc in child.children:
                        if gc.type == "identifier":
                            return gc.text.decode("utf-8", errors="replace")
            return None

        # Go: name is in type_spec grandchild
        if t == "type_declaration":
            for child in node.children:
                if child.type == "type_spec":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        return name_node.text.decode("utf-8", errors="replace")
            return None

        # JSON: pair node — key is the first string child; extract string_content
        if self.language == "json" and t == "pair":
            for child in node.children:
                if child.type == "string":
                    # prefer the string_content inner node (strips the quotes)
                    for subchild in child.children:
                        if subchild.type == "string_content":
                            return subchild.text.decode("utf-8", errors="replace")
                    # fallback: strip quote chars manually
                    raw = child.text.decode("utf-8", errors="replace")
                    return raw.strip('"\'')
            return None

        # YAML: block_mapping_pair or flow_pair — key is first child (flow_node → plain_scalar → string_scalar)
        if self.language == "yaml" and t in ("block_mapping_pair", "flow_pair"):
            key_node = node.children[0] if node.children else None
            if key_node:
                return key_node.text.decode("utf-8", errors="replace").rstrip(":").strip()
            return None

        # TOML: table — key is the bare_key (or quoted_key) child
        if self.language == "toml":
            if t == "table":
                for child in node.children:
                    if child.type in ("bare_key", "quoted_key"):
                        return child.text.decode("utf-8", errors="replace")
                return None
            if t == "pair":
                for child in node.children:
                    if child.type in ("bare_key", "quoted_key"):
                        return child.text.decode("utf-8", errors="replace")
                return None

        # C/C++: function — name from function_declarator → identifier (or qualified_identifier)
        if self.language in ("c", "cpp") and t == "function_definition":
            for child in node.children:
                if child.type == "function_declarator":
                    for subchild in child.children:
                        if subchild.type == "qualified_identifier":
                            return subchild.text.decode("utf-8", errors="replace")
                        if subchild.type == "identifier":
                            return subchild.text.decode("utf-8", errors="replace")
            return None

        # C/C++: typedef — name is the last type_identifier child
        if self.language in ("c", "cpp") and t == "type_definition":
            name = None
            for child in node.children:
                if child.type == "type_identifier":
                    name = child.text.decode("utf-8", errors="replace")
            return name

        # C++: class_specifier — name is the type_identifier child
        if self.language == "cpp" and t == "class_specifier":
            for child in node.children:
                if child.type == "type_identifier":
                    return child.text.decode("utf-8", errors="replace")
            return None

        # C++: namespace — name is namespace_identifier
        if self.language == "cpp" and t == "namespace_definition":
            for child in node.children:
                if child.type == "namespace_identifier":
                    return child.text.decode("utf-8", errors="replace")
            return None

        # C/C++: preprocessor include — full first line text
        if self.language in ("c", "cpp") and t == "preproc_include":
            return node.text.decode("utf-8", errors="replace").split("\n")[0].strip()[:80]

        # C/C++: macro define — identifier child
        if self.language in ("c", "cpp") and t == "preproc_def":
            for child in node.children:
                if child.type == "identifier":
                    return child.text.decode("utf-8", errors="replace")
            return None

        # Markdown: ATX section — name from atx_heading → inline
        if self.language == "markdown" and t == "section":
            for child in node.children:
                if child.type == "atx_heading":
                    for subchild in child.children:
                        if subchild.type == "inline":
                            return subchild.text.decode("utf-8", errors="replace").strip()
            return None

        # Markdown: setext heading — name from paragraph → inline
        if self.language == "markdown" and t == "setext_heading":
            for child in node.children:
                if child.type == "paragraph":
                    for gc in child.children:
                        if gc.type == "inline":
                            return gc.text.decode("utf-8", errors="replace").strip()
            return None

        # CSS/SCSS/Less: rule_set → selectors text; at-rules → first line; mixin → identifier
        if self.language in ("css", "scss", "less"):
            if t == "rule_set":
                for child in node.children:
                    if child.type == "selectors":
                        return child.text.decode("utf-8", errors="replace").strip()[:80]
                return None
            if t in ("media_statement", "keyframes_statement", "supports_statement"):
                return node.text.decode("utf-8", errors="replace").split("\n")[0].strip()[:80]
            if t == "mixin_statement":
                for child in node.children:
                    if child.type == "identifier":
                        return child.text.decode("utf-8", errors="replace")
                return None

        # HTML: element → STag → Name
        if self.language == "html" and t == "element":
            for child in node.children:
                if child.type == "STag":
                    for gc in child.children:
                        if gc.type == "Name":
                            return gc.text.decode("utf-8", errors="replace")
            return None

        # Bash: function_definition → word child
        if self.language == "bash" and t == "function_definition":
            for child in node.children:
                if child.type == "word":
                    return child.text.decode("utf-8", errors="replace")
            return None

        # Haskell: function/bind → variable child
        if self.language == "haskell" and t in ("function", "bind"):
            for child in node.children:
                if child.type == "variable":
                    return child.text.decode("utf-8", errors="replace")
            return None

        # OCaml: value_definition → let_binding → value_name; module_definition → module_binding → module_name
        if self.language == "ocaml":
            if t == "value_definition":
                for child in node.children:
                    if child.type == "let_binding":
                        for gc in child.children:
                            if gc.type == "value_name":
                                return gc.text.decode("utf-8", errors="replace")
                return None
            if t == "module_definition":
                for child in node.children:
                    if child.type == "module_binding":
                        for gc in child.children:
                            if gc.type == "module_name":
                                return gc.text.decode("utf-8", errors="replace")
                return None

        # Elixir: defmodule → arguments → alias; def/defp → arguments → call → identifier
        if self.language == "elixir" and t == "call":
            if not node.children:
                return None
            first = node.children[0]
            if first.type != "identifier":
                return None
            macro = first.text
            for child in node.children:
                if child.type == "arguments":
                    if macro in (b"defmodule", b"defprotocol", b"defimpl"):
                        for ac in child.children:
                            if ac.type in ("alias", "atom", "identifier"):
                                return ac.text.decode("utf-8", errors="replace")
                    elif macro in (b"def", b"defp", b"defmacro", b"defmacrop"):
                        for ac in child.children:
                            if ac.type == "call":
                                for gc in ac.children:
                                    if gc.type == "identifier":
                                        return gc.text.decode("utf-8", errors="replace")
                            if ac.type == "identifier":
                                return ac.text.decode("utf-8", errors="replace")
            return None

        # Erlang: fun_decl → function_clause → atom (function name)
        if self.language == "erlang" and t == "fun_decl":
            for child in node.children:
                if child.type == "function_clause":
                    for gc in child.children:
                        if gc.type == "atom":
                            return gc.text.decode("utf-8", errors="replace")
            return None

        # HCL: block → combine type + string labels (e.g., resource.aws_instance.web)
        if self.language == "hcl" and t == "block":
            parts = []
            for child in node.children:
                if child.type == "identifier":
                    parts.append(child.text.decode("utf-8", errors="replace"))
                elif child.type == "string_lit":
                    for gc in child.children:
                        if gc.type == "template_literal":
                            parts.append(gc.text.decode("utf-8", errors="replace"))
                elif child.type in ("block_start", "body", "block_end"):
                    break
            return ".".join(parts) if parts else None

        # Proto: message → message_name; service → service_name; rpc → rpc_name → identifier
        if self.language == "proto":
            if t == "message":
                for child in node.children:
                    if child.type == "message_name":
                        return child.text.decode("utf-8", errors="replace")
            if t == "service":
                for child in node.children:
                    if child.type == "service_name":
                        return child.text.decode("utf-8", errors="replace")
            if t == "rpc":
                for child in node.children:
                    if child.type == "rpc_name":
                        for gc in child.children:
                            if gc.type == "identifier":
                                return gc.text.decode("utf-8", errors="replace")
            return None

        # GraphQL: type_system_definition → type_definition → *_type_definition → name child
        if self.language == "graphql" and t == "type_system_definition":
            for child in node.children:
                if child.type == "type_definition":
                    for gc in child.children:
                        for ggc in gc.children:
                            if ggc.type == "name":
                                return ggc.text.decode("utf-8", errors="replace")
            return None

        # SQL: create_table/create_view/create_function → object_reference; create_index → identifier
        if self.language == "sql":
            if t in ("create_table", "create_view", "create_function"):
                for child in node.children:
                    if child.type == "object_reference":
                        return child.text.decode("utf-8", errors="replace")
            if t == "create_index":
                for child in node.children:
                    if child.type == "identifier":
                        return child.text.decode("utf-8", errors="replace")
            return None

        # XML: element → STag → Name
        if self.language == "xml" and t == "element":
            for child in node.children:
                if child.type == "STag":
                    for gc in child.children:
                        if gc.type == "Name":
                            return gc.text.decode("utf-8", errors="replace")
            return None

        # Svelte/Vue: fixed section names by node type
        if self.language in ("svelte", "vue"):
            if t == "script_element":
                return "script"
            if t == "style_element":
                return "style"
            if t == "template_element":
                return "template"
            return None

        # PowerShell: function_statement → function_name child
        if self.language == "powershell" and t == "function_statement":
            for child in node.children:
                if child.type == "function_name":
                    return child.text.decode("utf-8", errors="replace")
            return None

        # Dockerfile: from_instruction → image_spec child
        if self.language == "dockerfile" and t == "from_instruction":
            for child in node.children:
                if child.type == "image_spec":
                    return child.text.decode("utf-8", errors="replace")
            return None

        # Make: rule → targets child (first target name); skip special dot-targets
        if self.language == "make" and t == "rule":
            for child in node.children:
                if child.type == "targets":
                    name = child.text.decode("utf-8", errors="replace").split()[0]
                    return None if name.startswith(".") else name
            return None

        # Make: variable_assignment → word child (variable name)
        if self.language == "make" and t == "variable_assignment":
            for child in node.children:
                if child.type == "word":
                    return child.text.decode("utf-8", errors="replace")
            return None

        # Perl: subroutine → bareword; package → second package token
        if self.language == "perl":
            if t == "subroutine_declaration_statement":
                for child in node.children:
                    if child.type == "bareword":
                        return child.text.decode("utf-8", errors="replace")
                return None
            if t == "package_statement":
                count = 0
                for child in node.children:
                    if child.type == "package":
                        count += 1
                        if count == 2:
                            return child.text.decode("utf-8", errors="replace")
                return None

        # Zig: FnProto/VarDecl use IDENTIFIER (uppercase) not identifier
        if self.language == "zig" and t in ("FnProto", "VarDecl"):
            for child in node.children:
                if child.type == "IDENTIFIER":
                    return child.text.decode("utf-8", errors="replace")
            return None

        # Clojure: list_lit → second sym_lit (name after defn/def/ns/etc.)
        if self.language == "clojure" and t == "list_lit":
            sym_count = 0
            for child in node.children:
                if child.type == "sym_lit":
                    sym_count += 1
                    if sym_count == 2:
                        return child.text.decode("utf-8", errors="replace")
            return None

        # Fish: function_definition → word child
        if self.language == "fish" and t == "function_definition":
            for child in node.children:
                if child.type == "word":
                    return child.text.decode("utf-8", errors="replace")
            return None

        # Batch: function_definition → function_name child
        if self.language == "batch" and t == "function_definition":
            for child in node.children:
                if child.type == "function_name":
                    return child.text.decode("utf-8", errors="replace")
            return None

        # INI: section — name is from section_name → text child
        if self.language == "ini":
            if t == "section":
                for child in node.children:
                    if child.type == "section_name":
                        for subchild in child.children:
                            if subchild.type == "text":
                                return subchild.text.decode("utf-8", errors="replace")
                return None
            if t == "setting":
                for child in node.children:
                    if child.type == "setting_name":
                        return child.text.decode("utf-8", errors="replace")
                return None

        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf-8", errors="replace")
        # Fallback: try field name
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return name_node.text.decode("utf-8", errors="replace")
        return None

    def _get_signature(self, node, start_line: int) -> str:
        """Return the first source line of the node (stripped)."""
        idx = start_line - 1
        if 0 <= idx < len(self.lines):
            return self.lines[idx].strip()
        return ""

    def _strip_quotes(self, raw: str) -> str:
        """Remove surrounding triple or single/double quotes from a string literal."""
        s = raw.strip()
        for quote in ('"""', "'''", '"', "'"):
            if s.startswith(quote) and s.endswith(quote) and len(s) >= 2 * len(quote):
                return s[len(quote):-len(quote)]
        return s

    def _get_docstring(self, node) -> Optional[str]:
        """For Python, extract the first string literal in the body block."""
        if self.language != "python":
            return None

        # Find the block (body) child
        body = node.child_by_field_name("body")
        if body is None:
            return None

        # The first non-trivial child of the block may be a string (docstring) directly
        # or wrapped in an expression_statement, depending on tree-sitter version.
        for child in body.children:
            if child.type in ("newline", "indent", "comment"):
                continue
            if child.type == "string":
                raw = child.text.decode("utf-8", errors="replace")
                return self._strip_quotes(raw)
            if child.type == "expression_statement":
                for subchild in child.children:
                    if subchild.type == "string":
                        raw = subchild.text.decode("utf-8", errors="replace")
                        return self._strip_quotes(raw)
            # First real statement is not a docstring
            break

        return None
