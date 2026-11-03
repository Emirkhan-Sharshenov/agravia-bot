"""
Собирает zip для Yandex Cloud Functions: python -I deploy/yandex/build_zip.py

В архив попадают: yc_entry.py, backend/ (без venv/логов/QA), widget/ и зависимости,
скачанные под Linux x86_64 / Python 3.12 (колёса pydantic-core и rapidfuzz бинарные).
Результат: deploy/yandex/dist/agravia-bot.zip (+ размер в выводе).
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DIST = HERE / "dist"
WORK = DIST / "build"
REQ = ["fastapi==0.115.0", "httpx==0.27.2", "pydantic==2.9.2", "rapidfuzz==3.10.0", "snowballstemmer==3.1.1"]
SKIP_BACKEND = {"venv", "__pycache__", "logs", "qa", "api", ".env"}

shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True)
subprocess.check_call([
    sys.executable, "-m", "pip", "install", "--quiet", "--target", str(WORK),
    "--platform", "manylinux2014_x86_64", "--python-version", "3.12", "--implementation", "cp",
    "--only-binary=:all:", *REQ,
])
shutil.copy(HERE / "yc_entry.py", WORK / "yc_entry.py")
shutil.copytree(REPO / "backend", WORK / "backend", ignore=lambda d, names: [n for n in names if n in SKIP_BACKEND or n.endswith(".pyc")])
shutil.copytree(REPO / "widget", WORK / "widget")
for junk in list(WORK.rglob("__pycache__")) + list(WORK.rglob("*.dist-info")) + list(WORK.rglob("tests")):
    shutil.rmtree(junk, ignore_errors=True)

out = DIST / "agravia-bot.zip"
out.unlink(missing_ok=True)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for f in sorted(WORK.rglob("*")):
        if f.is_file():
            z.write(f, f.relative_to(WORK).as_posix())
print(f"{out} — {out.stat().st_size / 1024 / 1024:.1f} MB")
