"""Reset only after the old GUI and its file handles have completely exited."""
import argparse
import os
import subprocess
import sys
import time

from app.data_storage import DATA_ROOT, INSTALLATION_ROOT, ResetGuard, clear_app_data, other_programs_running


def launch_reset_helper():
    return subprocess.Popen([sys.executable,'-m','app.data_reset','--wait-pid',str(os.getpid())],
        cwd=str(INSTALLATION_ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def reset_and_restart(wait_pid):
    from app.single_instance import SingleInstanceManager
    with ResetGuard():
        deadline = time.monotonic()+60
        while SingleInstanceManager.process_is_running(wait_pid):
            if time.monotonic() >= deadline:
                raise RuntimeError('Кликер не успел завершить работу. Данные не удалены. Закройте программу и попробуйте снова.')
            time.sleep(.1)
        if other_programs_running(DATA_ROOT):
            raise RuntimeError('Открыто другое окно кликера. Закройте все окна программы и повторите сброс.')
        deadline = time.monotonic()+30
        while True:
            try:
                clear_app_data()
                break
            except OSError as error:
                # Windows may keep a deleted file pending, making its folder
                # temporarily non-empty even after the old process has exited.
                if (not isinstance(error,PermissionError) and
                        getattr(error,'winerror',None) not in (32,33,145)):
                    raise
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.1)
        environment = dict(os.environ,KGPM_AUTO_START='0')
        subprocess.Popen([sys.executable,'-m','app.ui'],cwd=str(INSTALLATION_ROOT),env=environment,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wait-pid',required=True,type=int)
    args = parser.parse_args()
    try:
        reset_and_restart(args.wait_pid)
    except Exception as error:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('Не удалось завершить сброс',
            str(error)+'\nОткройте программу снова. При повторной ошибке обратитесь к автору.',parent=root)
        root.destroy()


if __name__ == '__main__':
    main()
