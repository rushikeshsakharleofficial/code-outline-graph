import os
import sys
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
            self.indexer.db.delete_symbols_for_file(os.path.abspath(event.src_path))

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
                if os.path.exists(path):
                    self.indexer.index_file(path)
                else:
                    self.indexer.db.delete_symbols_for_file(os.path.abspath(path))
            except Exception as e:
                print(f"code-outline-graph watcher: failed to update {path}: {e}", file=sys.stderr)


class CodeWatcher:
    def __init__(self, indexer, project_path: str):
        self.indexer = indexer
        self.project_path = project_path
        self.observer = Observer()

    def start(self):
        handler = CodeChangeHandler(self.indexer)
        self.observer.schedule(handler, self.project_path, recursive=True)
        self.observer.start()

    def stop(self):
        self.observer.stop()
        self.observer.join()
