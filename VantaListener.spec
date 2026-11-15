from pathlib import Path

source = Path(SPECPATH)

analysis = Analysis(
    [str(source / "app.py")],
    datas=[(str(source / "licenses" / "*.txt"), "licenses")],
    hiddenimports=["websocket", "serial"],
)
archive = PYZ(analysis.pure)
exe = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="VantaListener",
    console=False,
    upx=False,
)
release = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    name="VantaListener",
    upx=False,
)
