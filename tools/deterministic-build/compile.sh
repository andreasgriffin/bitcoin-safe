
pip install poetry cleo crashtest requests xattr colorama pywin32-ctypes
pip freeze  | grep -E 'poetry|cleo|crashtest|requests|xattr|colorama|pywin32-ctypes' > tools/deterministic-build/requirements-poetry.in

python -m pip install 'pip<25.1' # pip-tools is not compatible with a newer version
pip install pip-tools
pip-compile tools/deterministic-build/requirements-build-base.in --generate-hashes --allow-unsafe
pip-compile tools/deterministic-build/requirements-poetry.in --generate-hashes 