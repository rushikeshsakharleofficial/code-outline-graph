from pathlib import Path

from code_outline_graph.paths import (
    PROJECT_DB_NAME,
    PROJECT_ENV_VAR,
    PROJECT_STATE_DIR,
    ensure_project_db_path,
    project_db_path,
    resolve_project_path,
)


def test_project_db_path_is_project_local(workspace_tmp):
    db_path = Path(project_db_path(str(workspace_tmp)))

    assert db_path == workspace_tmp / PROJECT_STATE_DIR / PROJECT_DB_NAME


def test_ensure_project_db_path_creates_state_dir(workspace_tmp):
    db_path = Path(ensure_project_db_path(str(workspace_tmp)))

    assert db_path.parent.is_dir()
    assert db_path == workspace_tmp / PROJECT_STATE_DIR / PROJECT_DB_NAME


def test_resolve_project_path_uses_env_when_no_path(workspace_tmp, monkeypatch):
    monkeypatch.setenv(PROJECT_ENV_VAR, str(workspace_tmp))

    assert Path(resolve_project_path()) == workspace_tmp
