"""Bounded technical data and narrowly scoped application-data removal."""
import json
import hashlib
import msvcrt
import os
from pathlib import Path
import threading
import time

INSTALLATION_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = INSTALLATION_ROOT / 'runtime'
HISTORY_LIMIT = 5000
RETENTION_DAYS = 7
DIAGNOSTICS_LIMIT = 200 * 1024 * 1024
LOG_LIMIT = 5 * 1024 * 1024
TECHNICAL_FOLDERS = {'debug', 'triggers', 'reset_diagnostics', 'backups'}


class ResetGuard:
    """Keep new application instances out while their shared data is reset."""
    def __init__(self, timeout_seconds=0, installation_root=INSTALLATION_ROOT):
        identity = hashlib.sha256(str(Path(installation_root).resolve()).casefold().encode('utf-8')).hexdigest()
        self.name = 'Local\\FountainDataReset-' + identity
        self.timeout_ms = int(timeout_seconds * 1000)
        self.handle = None

    def __enter__(self):
        import ctypes
        from app.single_instance import kernel32
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p,ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        self.handle = kernel32.CreateMutexW(None,False,self.name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        result = kernel32.WaitForSingleObject(self.handle,self.timeout_ms)
        if result not in (0,0x80):
            kernel32.CloseHandle(self.handle)
            self.handle = None
            raise RuntimeError('Сброс данных ещё выполняется. Подождите немного и откройте программу снова.')
        return self

    def __exit__(self,*_):
        from app.single_instance import kernel32
        kernel32.ReleaseMutex(self.handle)
        kernel32.CloseHandle(self.handle)
        self.handle = None


def validate_data_root(root, installation_root=INSTALLATION_ROOT):
    root = Path(root).absolute()
    expected = Path(installation_root).absolute() / 'runtime'
    if root != expected or root.is_symlink() or root.is_junction():
        raise ValueError('Only the application runtime directory may be cleared')
    if root.resolve() != expected.resolve():
        raise ValueError('Application data path changed')
    return root.resolve()


def data_tree(root):
    """Do not follow links or junctions, including links to another local folder."""
    if not root.exists():
        return
    for folder, directories, files in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories
                          if not (Path(folder)/name).is_symlink() and not (Path(folder)/name).is_junction()]
        yield Path(folder), files


def data_files(root):
    for folder,files in data_tree(root):
        for name in files:
            path = folder/name
            if not path.is_symlink() and path.resolve().is_relative_to(root):
                yield path


def maintain_data(root=DATA_ROOT, *, installation_root=INSTALLATION_ROOT, now=None,
                  diagnostics_limit=DIAGNOSTICS_LIMIT, log_limit=LOG_LIMIT):
    root = validate_data_root(root, installation_root)
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.cleanup.lock').open('a+b') as guard:
        guard.seek(0,2)
        if guard.tell() == 0:
            guard.write(b'0')
            guard.flush()
        guard.seek(0)
        try:
            msvcrt.locking(guard.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            return 0
        try:
            return _maintain_unlocked(root,now,diagnostics_limit,log_limit)
        finally:
            guard.seek(0)
            msvcrt.locking(guard.fileno(),msvcrt.LK_UNLCK,1)


def _maintain_unlocked(root,now,diagnostics_limit,log_limit):
    now = time.time() if now is None else now
    technical = []
    removed = 0
    for path in data_files(root):
        try:
            stat = path.stat()
            parts = set(path.relative_to(root).parts[:-1])
            if parts & TECHNICAL_FOLDERS:
                if now-stat.st_mtime > RETENTION_DAYS*86400:
                    path.unlink()
                    removed += 1
                else:
                    technical.append((stat.st_mtime,stat.st_size,path))
            elif path.suffix in {'.log','.jsonl'}:
                if now-stat.st_mtime > RETENTION_DAYS*86400:
                    path.unlink()
                    removed += 1
                elif stat.st_size > log_limit:
                    with path.open('r+b') as stream:
                        stream.seek(-log_limit,2)
                        tail = stream.read().split(b'\n',1)[-1]
                        stream.seek(0)
                        stream.write(tail)
                        stream.truncate()
            elif 'hotkey_commands' in parts and now-stat.st_mtime > 86400:
                path.unlink()
                removed += 1
        except OSError:
            # A file being written or held by Windows can be retried next time.
            continue
    total = sum(size for _,size,_ in technical)
    for modified,size,path in sorted(technical):
        if total <= diagnostics_limit:
            break
        if now-modified < 60:
            continue
        try:
            path.unlink()
            total -= size
            removed += 1
        except OSError:
            pass
    if root.exists():
        for path in sorted((folder for folder,_ in data_tree(root)),key=lambda item:len(item.parts),reverse=True):
            if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root):
                continue
            if not (set(path.relative_to(root).parts) & TECHNICAL_FOLDERS):
                continue
            try:
                if now-path.stat().st_mtime >= 60:
                    path.rmdir()
            except OSError:
                pass
    return removed


def other_programs_running(root=DATA_ROOT, current_pid=None):
    from app.single_instance import SingleInstanceManager
    current_pid = os.getpid() if current_pid is None else current_pid
    for path in data_files(Path(root).resolve()):
        if path.name != 'instance_state.json':
            continue
        try:
            pid = int(json.loads(path.read_text(encoding='utf-8'))['pid'])
            if pid != current_pid and SingleInstanceManager.process_is_running(pid):
                return True
        except (OSError,ValueError,KeyError,TypeError):
            continue
    return False


def clear_app_data(root=DATA_ROOT, *, installation_root=INSTALLATION_ROOT):
    root = validate_data_root(root, installation_root)
    if not root.exists():
        return
    paths, pending = [], [root]
    while pending:
        for path in pending.pop().iterdir():
            if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root):
                raise ValueError('Application data contains a link; reset was cancelled')
            paths.append(path)
            if path.is_dir():
                pending.append(path)
    for path in sorted(paths,key=lambda item:len(item.parts),reverse=True):
        if not path.resolve().is_relative_to(root):
            raise ValueError('Application data path changed')
        if path.is_dir():
            try:
                path.rmdir()
            except FileNotFoundError:
                pass
        else:
            path.unlink(missing_ok=True)
    try:
        root.rmdir()
    except FileNotFoundError:
        pass


class DataMaintenance:
    def __init__(self, root=DATA_ROOT):
        self.root = root
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run,name='kgpm-data-maintenance',daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                maintain_data(self.root)
            except (OSError,ValueError):
                pass
            self.stop.wait(300)

    def close(self):
        self.stop.set()

