"""Tree-sitter-based multi-language symbol parser."""

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
}


def detect_language(file_path: str) -> Optional[str]:
    """Return tree-sitter language name for the file extension, or None."""
    suffix = Path(file_path).suffix
    return LANGUAGE_MAP.get(suffix)


class SymbolParser:
    """Facade that manages per-language parsers and dispatches parse requests."""

    def __init__(self) -> None:
        self._parsers: dict[str, object] = {}

    def _get_parser(self, language: str):
        if language not in self._parsers:
            self._parsers[language] = get_parser(language)
        return self._parsers[language]

    def parse_file(self, file_path: str) -> list[Symbol]:
        """Parse a file and return extracted symbols."""
        language = detect_language(file_path)
        if language is None:
            return []

        source = Path(file_path).read_bytes()
        parser = self._get_parser(language)
        tree = parser.parse(source)

        extractor = SymbolExtractor(source=source, language=language, file_path=file_path)
        return extractor.extract(tree.root_node)


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
