# -*- mode: python ; coding: utf-8 -*-
import os
import site
import sys
import platform

# 获取 site-packages 路径
# 这里我们假设是在 venv 环境下运行 PyInstaller
# 获取 mapproxy 的安装路径
import mapproxy
mapproxy_path = os.path.dirname(mapproxy.__file__)
spec_dir = os.path.abspath(globals().get('SPECPATH', os.getcwd()))
project_root = os.path.abspath(os.path.join(spec_dir, os.pardir))
entry_script = os.path.join(project_root, 'src', 'ui', 'gui_launcher.py')
configs_dir = os.path.join(project_root, 'configs')
requirements_file = os.path.join(project_root, 'requirements.txt')

block_cipher = None

# 需要打包的所有数据文件
datas = [
    (configs_dir, 'mapproxy_config'),
    (requirements_file, '.'),
    # 显式包含 MapProxy 的配置文件和模板
    (os.path.join(mapproxy_path, 'config', 'config-schema.json'), os.path.join('mapproxy', 'config')),
    (os.path.join(mapproxy_path, 'service', 'templates'), os.path.join('mapproxy', 'service', 'templates')),
]

# 隐藏导入：确保 waitress 和 mapproxy 的核心模块被包含
hiddenimports = [
    'tkinter', 
    'json', 
    'subprocess', 
    'threading', 
    'queue', 
    'socket', 
    'shutil',
    'waitress',
    'mapproxy',
    'mapproxy.wsgiapp',
    'yaml',
    'PIL',
    'psutil',
    'typing_extensions',
    'charset_normalizer',
]

# 平台特定的排除项
excludes = [
    'venv', 
    '.env', 
    '__pycache__', 
    'packages', 
    'cache_data', 
    'logs', 
    'dist', 
    'build',
    'tests',
    'docs'
]

a = Analysis(
    [entry_script],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
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
    name='MapProxyLauncher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI 程序不显示控制台 (Linux 下也会生效，但不影响运行)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
