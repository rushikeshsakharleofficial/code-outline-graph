import shutil
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def workspace_tmp():
    base = Path.cwd() / ".test-tmp"
    base.mkdir(exist_ok=True)
    path = base / uuid.uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        resolved_base = base.resolve()
        resolved_path = path.resolve()
        if resolved_base in resolved_path.parents:
            shutil.rmtree(resolved_path, ignore_errors=True)
