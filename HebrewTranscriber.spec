# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['HebrewTranscriber/main.py'],
    pathex=['g:\\Projects\\Hebrew-Video-Transcriber'],
    binaries=[],
    datas=[
        ('HebrewTranscriber/ui/styles.qss', 'ui'),
    ],
    hiddenimports=[
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'faster_whisper',
        'ctranslate2',
        'huggingface_hub',
        'tokenizers',
        'av',
        'playwright',
        'fpdf2',
        'python_bidi',
        'arabic_reshaper',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'tkinter', 'matplotlib', 'IPython', 'pytest', 'scipy', 'spacy', 'sklearn', 'nltk', 'torch', 'tensorflow', 'keras', 'pandas', 'jupyter', 'notebook', 'datasets', 'transformers'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='HebrewTranscriber',
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
    icon=None,
)
