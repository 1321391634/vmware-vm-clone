# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'openpyxl',
        'keyring',
        'keyring.backends',
        'numpy',
        'PIL',
        'lxml',
        'pandas',
        'matplotlib',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DRender',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtNetworkAuth',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtPositioning',
        'PySide6.QtPrintSupport',
        'PySide6.QtQuick',
        'PySide6.QtQuick3D',
        'PySide6.QtQuickWidgets',
        'PySide6.QtRemoteObjects',
        'PySide6.QtScxml',
        'PySide6.QtSensors',
        'PySide6.QtSerialBus',
        'PySide6.QtSerialPort',
        'PySide6.QtSpatialAudio',
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtUiTools',
        'PySide6.QtWebChannel',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebSockets',
    ],
    noarchive=False,
    optimize=0,
)


_UNUSED_PYSIDE6_PATHS = (
    "pyside6/qt6network.dll",
    "pyside6/qtnetwork.pyd",
    "pyside6/qt6opengl.dll",
    "pyside6/qtopengl.pyd",
    "pyside6/qt6pdf.dll",
    "pyside6/qtpdf.pyd",
    "pyside6/qt6qml.dll",
    "pyside6/qtqml.pyd",
    "pyside6/qt6qmlmeta.dll",
    "pyside6/qtqmlmeta.pyd",
    "pyside6/qt6qmlmodels.dll",
    "pyside6/qtqmlmodels.pyd",
    "pyside6/qt6qmlworkerscript.dll",
    "pyside6/qtqmlworkerscript.pyd",
    "pyside6/qt6quick.dll",
    "pyside6/qtquick.pyd",
    "pyside6/qt6virtualkeyboard.dll",
    "pyside6/qtvirtualkeyboard.pyd",
    "pyside6/opengl32sw.dll",
    "pyside6/plugins/networkinformation/",
    "pyside6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
    "pyside6/plugins/imageformats/qpdf.dll",
    "pyside6/plugins/imageformats/qsvg.dll",
)


def _prune_unused_qt(entries):
    return [
        entry
        for entry in entries
        if not any(
            token in entry[0].replace("\\", "/").lower()
            for token in _UNUSED_PYSIDE6_PATHS
        )
    ]


a.binaries = _prune_unused_qt(a.binaries)
a.datas = _prune_unused_qt(a.datas)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='vm-clone',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
