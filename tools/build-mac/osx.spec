# -*- mode: python -*-

from pathlib import Path
import platform
import site
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs
from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.building.osx import BUNDLE

import sys, os

import certifi



# Function to determine target architecture based on Python's running architecture
def get_target_arch():
    arch = platform.machine()
    if arch == 'x86_64':
        return 'x86_64'
    elif arch in ('arm', 'arm64', 'aarch64'):
        return 'arm64'
    else:
        return 'universal2'  # Defaulting to universal for other cases (as a fallback)
target_arch = get_target_arch()
print(f"Building for {target_arch=}")



EXECUTABLE_NAME=f"run_Bitcoin_Safe"
PACKAGE_NAME='Bitcoin Safe.app'
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
hiddenimports += collect_submodules('hwilib') # otherwise hwilib doesnt get packaged

packages_with_dlls = [ 'bdkpython', 'nostr_sdk', 'pyzbar', 'pygame', "numpy.libs", "cv2"]

binaries = []
# Workaround for "Retro Look":
binaries += [b for b in collect_dynamic_libs('PyQt6') if 'macstyle' in b[0]]
for package_with_dlls in packages_with_dlls:
    binaries += collect_dynamic_libs(package_with_dlls)
# add libusb, etc:
binaries += [(f"{PROJECT_ROOT}/{PYPKG}/*.dylib", ".")]
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
    name=EXECUTABLE_NAME,
    debug=True,
    strip=False,
    upx=True,
    icon=ICONS_FILE,
    console=False,
    target_arch=target_arch,  # TODO investigate building 'universal2'
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
        'CFBundleExecutable': EXECUTABLE_NAME,
        'CFBundleURLTypes': [
            {
                'CFBundleURLName': 'bitcoin',
                'CFBundleURLSchemes': ['bitcoin'],
            }
        ],
        'LSMinimumSystemVersion': '11',
        'NSCameraUsageDescription': 'Bitcoin Safe would like to access the camera to scan for QR codes',
    },
)
