# -*- mode: python -*-

from pathlib import Path
import site
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs
from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
import sys, os

import certifi

PYPKG="bitcoin_safe"
PROJECT_ROOT = "C:/bitcoin_safe"
ICONS_FILE=f"{PROJECT_ROOT}/tools/resources/icon.ico"

cmdline_name = os.environ.get("bitcoin_safe_CMDLINE_NAME")
if not cmdline_name:
    raise Exception('no name')

# see https://github.com/pyinstaller/pyinstaller/issues/2005
hiddenimports = []
hiddenimports += collect_submodules('pkg_resources')  # workaround for https://github.com/pypa/setuptools/issues/1963
hiddenimports += collect_submodules('hwilib') # otherwise hwilib doesnt get packaged


packages_with_dlls = [ 'bdkpython', 'nostr_sdk', 'pyzbar', 'pygame', "numpy.libs", "cv2"]

binaries = []
# Workaround for "Retro Look":
binaries += [b for b in collect_dynamic_libs('PyQt6') if 'windows' in b[0]]
for package_with_dlls in packages_with_dlls:
    binaries += collect_dynamic_libs(package_with_dlls)
# add libusb, etc:
binaries += [(f"{PROJECT_ROOT}/{PYPKG}/*.dll", '.')]
print(f"Included binaries: {binaries}")

datas = [
    (certifi.where(), "certifi/"), # necessary on mac to avail ssl errors
    (f"{PROJECT_ROOT}/{PYPKG}/gui/icons/*", f"{PYPKG}/gui/icons"),
    (f"{PROJECT_ROOT}/{PYPKG}/gui/icons/hardware_signers/*", f"{PYPKG}/gui/icons/hardware_signers"),
    (f"{PROJECT_ROOT}/{PYPKG}/gui/icons/hardware_signers/generated/*", f"{PYPKG}/gui/icons/hardware_signers/generated"),
    (f"{PROJECT_ROOT}/{PYPKG}/gui/screenshots/*", f"{PYPKG}/gui/screenshots"),
    (f"{PROJECT_ROOT}/{PYPKG}/gui/locales/*", f"{PYPKG}/gui/locales"), 
    (f"{PROJECT_ROOT}/{PYPKG}/gui/demo_wallets/REGTEST/*", f"{PYPKG}/gui/demo_wallets/REGTEST"), 
    (f"{PROJECT_ROOT}/{PYPKG}/gui/demo_wallets/SIGNET/*", f"{PYPKG}/gui/demo_wallets/SIGNET"), 
    (f"{PROJECT_ROOT}/{PYPKG}/gui/demo_wallets/TESTNET/*", f"{PYPKG}/gui/demo_wallets/TESTNET"), 
    (f"{PROJECT_ROOT}/{PYPKG}/gui/demo_wallets/TESTNET4/*", f"{PYPKG}/gui/demo_wallets/TESTNET4"), 
]

##### data of included modules 
# Get the site-packages directory
site_packages_dir = Path([s for s in site.getsitepackages() if "site-packages" in s][0])
print(f"{site_packages_dir=}")

# Example: Collect all SVG files from a module in site-packages 
icon_paths = [Path("bitcoin_qr_tools/gui/icons"),
              Path("bitcoin_usb/icons"),
              Path("bitcoin_usb/device_scripts"),  # for the python files that are not directly imported, but used via manual python execution 
              Path("bitcoin_nostr_chat/ui/icons")
              ]
for icon_path in icon_paths:
    datas += [(f"{site_packages_dir/icon_path / '*'}", f"{icon_path}"),] 

print(f"{datas=}")




# We don't put these files in to actually include them in the script but to make the Analysis method scan them for imports
a = Analysis([f"../../{PYPKG}/__main__.py" ],
             pathex=[f"{PROJECT_ROOT}/{PYPKG}"] + [f"{PROJECT_ROOT}/{package_with_dlls}" for package_with_dlls in packages_with_dlls],
             binaries=binaries,
             datas=datas,
             hiddenimports=hiddenimports,
             hookspath=[])


# http://stackoverflow.com/questions/19055089/pyinstaller-onefile-warning-pyconfig-h-when-importing-scipy-or-scipy-signal
for d in a.datas:
    if 'pyconfig' in d[0]:
        a.datas.remove(d)
        break
print(f"Included datas: {datas}")

# Strip out parts of Qt that we never use. Reduces binary size by tens of MBs. see #4815
qt_bins2remove=(
    r'pyqt6\qt6\qml',
    r'pyqt6\qt6\bin\qt6quick',
    r'pyqt6\qt6\bin\qt6qml',
    r'pyqt6\qt6\bin\qt6multimediaquick',
    r'pyqt6\qt6\bin\qt6pdfquick',
    r'pyqt6\qt6\bin\qt6positioning',
    r'pyqt6\qt6\bin\qt6spatialaudio',
    r'pyqt6\qt6\bin\qt6shadertools',
    r'pyqt6\qt6\bin\qt6sensors',
    r'pyqt6\qt6\bin\qt6web',
    r'pyqt6\qt6\bin\qt6test',
)
print("Removing Qt binaries:", *qt_bins2remove)
for x in a.binaries.copy():
    for r in qt_bins2remove:
        if x[0].lower().startswith(r):
            a.binaries.remove(x)
            print('----> Removed x =', x)

qt_data2remove=(
    r'pyqt6\qt6\translations\qtwebengine_locales',
    r'pyqt6\qt6\qml',
)
print("Removing Qt datas:", *qt_data2remove)
for x in a.datas.copy():
    for r in qt_data2remove:
        if x[0].lower().startswith(r):
            a.datas.remove(x)
            print('----> Removed x =', x)

# not reproducible (see #7739):
print("Removing *.dist-info/ from datas:")
for x in a.datas.copy():
    if ".dist-info\\" in x[0].lower():
        a.datas.remove(x)
        print('----> Removed x =', x)


# hotfix for #3171 (pre-Win10 binaries)
a.binaries = [x for x in a.binaries if not x[1].lower().startswith(r'c:\windows')]

pyz = PYZ(a.pure)


#####
# "standalone" exe with all dependencies packed into it

# exe_standalone = EXE(
#     pyz,
#     a.scripts,
#     a.binaries,
#     a.datas,
#     name=os.path.join("build", "pyi.win32", PYPKG, f"{cmdline_name}.exe"),
#     debug=False,
#     strip=False,
#     upx=False,
#     icon=ICONS_FILE,
#     console=False)
    # console=True makes an annoying black box pop up, but it does make bitcoin_safe output command line commands, with this turned off no output will be given but commands can still be used

exe_portable = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas + [('is_portable', '../../README.md', 'DATA')],
    name=os.path.join("build", "pyi.win32", PYPKG, f"{cmdline_name}-portable.exe"),
    debug=False,
    strip=False,
    upx=False,
    icon=ICONS_FILE,
    console=False)

#####
# exe and separate files that NSIS uses to build installer "setup" exe

exe_inside_setup_noconsole = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=os.path.join("build", "pyi.win32", PYPKG, f"{cmdline_name}.exe"),
    debug=False,
    strip=False,
    upx=False,
    icon=ICONS_FILE,
    console=False)

exe_inside_setup_console = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=os.path.join("build", "pyi.win32", PYPKG, f"{cmdline_name}-debug.exe"),
    debug=False,
    strip=False,
    upx=False,
    icon=ICONS_FILE,
    console=True)

coll = COLLECT(
    exe_inside_setup_noconsole,
    exe_inside_setup_console,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    debug=False,
    icon=ICONS_FILE,
    console=False,
    name=os.path.join('dist', PYPKG))
