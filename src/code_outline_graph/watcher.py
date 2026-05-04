import os
import threading
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from .parser import detect_language


class CodeChangeHandler(FileSystemEventHandler):
    def __init__(self, indexer, debounce_ms: int = 500):
        self.indexer = indexer
        self.debounce_s = debounce_ms / 1000.0
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()
        self._timer = None

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self.indexer.db.delete_symbols_for_file(event.src_path)

    def _schedule(self, path: str):
        if not detect_language(path):
            return
        with self._lock:
            self._pending[path] = time.time()
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_s, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self):
        with self._lock:
            paths = list(self._pending.keys())
            self._pending.clear()
        for path in paths:
            try:
                self.indexer.index_file(path)
            except Exception:
                pass


class GitHeadHandler(FileSystemEventHandler):
    def __init__(self, indexer, project_path: str):
        self.indexer = indexer
        self.project_path = project_path
        self._timer = None
        self._lock = threading.Lock()

    def on_modified(self, event):
        if event.src_path.endswith("HEAD"):
            self._schedule_reindex()

    def on_created(self, event):
        if event.src_path.endswith("HEAD"):
            self._schedule_reindex()

    def _schedule_reindex(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(2.0, self._reindex)
            self._timer.daemon = True
            self._timer.start()

    def _reindex(self):
        try:
            self.indexer.index_project(self.project_path)
        except Exception:
            pass


class CodeWatcher:
    def __init__(self, indexer, project_path: str):
        self.indexer = indexer
        self.project_path = project_path
        self.observer = Observer()

    def start(self):
        handler = CodeChangeHandler(self.indexer)
        self.observer.schedule(handler, self.project_path, recursive=True)
        git_dir = os.path.join(self.project_path, ".git")
        if os.path.isdir(git_dir):
            git_handler = GitHeadHandler(self.indexer, self.project_path)
            self.observer.schedule(git_handler, git_dir, recursive=False)
        self.observer.start()

    def stop(self):
        self.observer.stop()
        self.observer.join()
