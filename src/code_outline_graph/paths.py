import os


PROJECT_STATE_DIR = ".code-outline-graph"
PROJECT_DB_NAME = "index.db"
PROJECT_ENV_VAR = "CODE_OUTLINE_GRAPH_PROJECT"


def resolve_project_path(project_path: str | None = None) -> str:
    """Resolve the project root used to scope index state."""
    path = project_path or os.environ.get(PROJECT_ENV_VAR) or "."
    return os.path.abspath(os.path.expanduser(path))


def project_db_path(project_path: str | None = None) -> str:
    """Return the project-local SQLite index path."""
    return os.path.join(resolve_project_path(project_path), PROJECT_STATE_DIR, PROJECT_DB_NAME)


def ensure_project_db_path(project_path: str | None = None) -> str:
    """Create the project state directory and return the SQLite index path."""
    db_path = project_db_path(project_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return db_path
