from setuptools import setup, find_packages, find_namespace_packages


with open("requirements.txt") as f:
    install_reqs = f.read().strip().split("\n")

# Filter out comments/hashes
reqs = []
for req in install_reqs:
    if req.startswith("#") or req.startswith("    --hash="):
        continue
    reqs.append(str(req).rstrip(" \\"))


with open("README.md", "r") as fh:
    long_description = fh.read()


setup(
    name="bitcoin_safe",
    version="0.1.0",
    author="Andreas Griffin",
    author_email="andreasgriffin@proton.me",
    description="A bitcoin wallet for the whole family.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/andreasgriffin/bitcoin-safe",
    packages=find_namespace_packages("bitcoin_safe", include=["bitcoin_safe.*"]),
    package_dir={"": "bitcoin_safe"},
    install_requires=reqs,
    classifiers=[
        "Development Status :: 3 - Alpha",  # Replace with the appropriate development status
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Topic :: Software Development :: User Interfaces",
        "Topic :: Internet",
        "Topic :: Security :: Cryptography",
        "Topic :: Office/Business :: Financial :: Accounting",
    ],
    python_requires=">=3.7,<4.0",
    entry_points={
        "console_scripts": [
            "bitcoin_safe=bitcoin_safe.main:main",
        ],
    },
)
