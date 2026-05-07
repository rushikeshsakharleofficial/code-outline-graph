from code_outline_graph.parser import SymbolParser, detect_language


def test_python_parser_extracts_symbols_and_docstrings(workspace_tmp):
    path = workspace_tmp / "service.py"
    path.write_text(
        "\n".join(
            [
                "import os",
                "VALUE = 1",
                "class Service:",
                "    \"\"\"Service docs.\"\"\"",
                "    def run(self, item):",
                "        return item",
                "",
                "def helper(x):",
                "    \"\"\"Helper docs.\"\"\"",
                "    return x",
            ]
        )
        + "\n"
    )

    symbols = SymbolParser().parse_file(str(path))
    by_name = {symbol.name: symbol for symbol in symbols}

    assert by_name["Service"].kind == "class"
    assert by_name["Service"].docstring == "Service docs."
    assert by_name["run"].kind == "method"
    assert by_name["run"].parent_name == "Service"
    assert by_name["helper"].kind == "function"
    assert by_name["helper"].docstring == "Helper docs."
    assert by_name["VALUE"].kind == "variable"


def test_detect_language_handles_special_filenames_and_unsupported_files(workspace_tmp):
    dockerfile = workspace_tmp / "Dockerfile"
    dockerfile.write_text("FROM python:3.12\n")
    notes = workspace_tmp / "notes.unknown"
    notes.write_text("hello\n")

    assert detect_language(str(dockerfile)) == "dockerfile"
    assert detect_language(str(notes)) is None


def test_sqlite_schema_parser_extracts_tables(workspace_tmp):
    import sqlite3

    db_path = workspace_tmp / "app.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    conn.close()

    symbols = SymbolParser().parse_file(str(db_path))

    assert any(symbol.kind == "table" and symbol.name == "users" for symbol in symbols)
