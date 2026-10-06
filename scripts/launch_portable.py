"""Entry point for the self-contained Windows archive; never enables clicks."""
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ['PYTHONNOUSERSITE'] = '1'
    os.environ['PADDLE_PDX_CACHE_HOME'] = str(root / '.models')
    if '--self-test' in sys.argv:
        import tkinter as tk
        from PIL import Image
        from app.production_ocr import ProductionOcrEngines
        from app.version import APP_VERSION
        window = tk.Tk()
        window.withdraw()
        window.destroy()
        report = ProductionOcrEngines().warm_up(Image.new('RGB', (183, 42), '#505050'))
        report.update(version=APP_VERSION, python=sys.executable, real_taps=0)
        print(json.dumps(report, ensure_ascii=False))
        return
    runtime = root / 'runtime'
    runtime.mkdir(exist_ok=True)
    output = (runtime / 'launcher.log').open('a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = output
    try:
        from app.ui import main as launch
        launch()
    except Exception:
        traceback.print_exc()
        import tkinter.messagebox as messagebox
        messagebox.showerror('Не удалось запустить Фонтан',
            'Проверьте, что архив полностью распакован.\n'
            'Если ошибка повторяется, передайте автору файл runtime/launcher.log.')
        raise


if __name__ == '__main__':
    main()
