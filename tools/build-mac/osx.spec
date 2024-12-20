# -*- mode: python -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs
from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.building.osx import BUNDLE

import sys, os

PACKAGE_NAME='Bitcoin_Safe.app'
PYPKG='bitcoin_safe'
PROJECT_ROOT = os.path.abspath(".")
ICONS_FILE=f"{PROJECT_ROOT}/tools/resources/icon.icns"


VERSION = os.environ.get("BITCOIN_SAFE_VERSION")
if not VERSION:
    raise Exception('no version')

block_cipher = None

# see https://github.com/pyinstaller/pyinstaller/issues/2005
hiddenimports = []
hiddenimports += collect_submodules('pkg_resources')  # workaround for https://github.com/pypa/setuptools/issues/1963

packages_with_dlls = [ 'bdkpython', 'nostr_sdk', 'pyzbar', 'pygame', "numpy.libs", "cv2"]

binaries = []
# Workaround for "Retro Look":
binaries += [b for b in collect_dynamic_libs('PyQt6') if 'macstyle' in b[0]]
for package_with_dlls in packages_with_dlls:
    binaries += collect_dynamic_libs(package_with_dlls)
# add libsecp256k1, libusb, etc:
binaries += [(f"{PROJECT_ROOT}/{PYPKG}/*.dylib", ".")]
print(f"Included binaries: {binaries}")



datas = [
    (f"{PROJECT_ROOT}/{PYPKG}/gui/icons/*", f"{PYPKG}/gui/icons"),
    (f"{PROJECT_ROOT}/{PYPKG}/gui/icons/hardware_signers/*", f"{PYPKG}/gui/icons/hardware_signers"),
    (f"{PROJECT_ROOT}/{PYPKG}/gui/icons/hardware_signers/generated/*", f"{PYPKG}/gui/icons/hardware_signers/generated"),
    (f"{PROJECT_ROOT}/{PYPKG}/gui/screenshots/*", f"{PYPKG}/gui/screenshots"),
    (f"{PROJECT_ROOT}/{PYPKG}/gui/locales/*", f"{PYPKG}/gui/locales"),
    # (f"{PROJECT_ROOT}/{PYPKG}/lnwire/*.csv", f"{PYPKG}/lnwire"),
    # (f"{PROJECT_ROOT}/{PYPKG}/wordlist/english.txt", f"{PYPKG}/wordlist"),
    # (f"{PROJECT_ROOT}/{PYPKG}/wordlist/slip39.txt", f"{PYPKG}/wordlist"),
    # (f"{PROJECT_ROOT}/{PYPKG}/locale", f"{PYPKG}/locale"),
    # (f"{PROJECT_ROOT}/{PYPKG}/plugins", f"{PYPKG}/plugins"),
    # (f"{PROJECT_ROOT}/{PYPKG}/gui/icons", f"{PYPKG}/gui/icons"),
]



# We don't put these files in to actually include them in the script but to make the Analysis method scan them for imports
a = Analysis([f"{PROJECT_ROOT}/{PYPKG}/__main__.py",  ],
             pathex=[f"{PROJECT_ROOT}/{PYPKG}"] + [f"{PROJECT_ROOT}/{package_with_dlls}" for package_with_dlls in packages_with_dlls],
             binaries=binaries,
             datas=datas,
             hiddenimports=hiddenimports,
             hookspath=[])
print(a)

# http://stackoverflow.com/questions/19055089/pyinstaller-onefile-warning-pyconfig-h-when-importing-scipy-or-scipy-signal
for d in a.datas:
    if 'pyconfig' in d[0]:
        a.datas.remove(d)
        break
print(f"Included datas: {datas}")

# Strip out parts of Qt that we never use. Reduces binary size by tens of MBs. see #4815
qt_bins2remove=(
    'pyqt6/qt6/qml',
    'pyqt6/qt6/lib/qtqml',
    'pyqt6/qt6/lib/qtquick',
    'pyqt6/qt6/lib/qtshadertools',
    'pyqt6/qt6/lib/qtspatialaudio',
    'pyqt6/qt6/lib/qtmultimediaquick',
    'pyqt6/qt6/lib/qtweb',
    'pyqt6/qt6/lib/qtpositioning',
    'pyqt6/qt6/lib/qtsensors',
    'pyqt6/qt6/lib/qtpdfquick',
    'pyqt6/qt6/lib/qttest',
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

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=f"run_{PACKAGE_NAME}",
    debug=True,
    strip=False,
    upx=True,
    icon=ICONS_FILE,
    console=False,
    target_arch='x86_64',  # TODO investigate building 'universal2'
)

app = BUNDLE(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    version=VERSION,
    name=PACKAGE_NAME,
    icon=ICONS_FILE,
    bundle_identifier=None,
    info_plist={
        'NSHighResolutionCapable': 'True',
        'NSSupportsAutomaticGraphicsSwitching': 'True',
        'CFBundleURLTypes':
            [{
                'CFBundleURLName': 'bitcoin',
                'CFBundleURLSchemes': ['bitcoin', ],
            }],
        'LSMinimumSystemVersion': '11',
        'NSCameraUsageDescription': 'Bitcoin_Safe would like to access the camera to scan for QR codes',
    },
)
