# PyInstaller onedir specification for the standalone CN runtime.
# The build helper supplies the staged source as the current working directory.

from pathlib import Path
import json

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


# build_runtime.py evaluates this spec with the staged checkout as cwd. Using
# cwd keeps the spec correct even when PyInstaller copies the spec to --specpath.
source_root = Path.cwd().resolve()
config_path = source_root / "cn" / "packaging" / "config" / "frozen_imports.json"
config = json.loads(config_path.read_text(encoding="utf-8"))

hiddenimports = list(config.get("hidden_imports", []))
for package in config.get("data_packages", []):
    # Dynamic discovery is needed because Hermes registers tools and routers at
    # import time. The package list is kept in the overlay so it can be
    # reviewed independently for each source revision.
    hiddenimports.extend(collect_submodules(package))

datas = []
for package in config.get("data_packages", []):
    datas.extend(collect_data_files(package, include_py_files=False))

for relative in ("skills", "optional-skills", "plugins"):
    directory = source_root / relative
    if directory.is_dir():
        datas.append((str(directory), relative))

analysis = Analysis(
    [str(source_root / "hermes_cli" / "main.py")],
    pathex=[str(source_root)],
    binaries=[],
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="hermes-agent-cn-runtime",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="hermes-agent-cn-runtime",
)
