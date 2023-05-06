from setuptools import setup, find_packages

setup(
    name="bitcoin_safe",
    version="0.1",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "bitcoin_safe=bitcoin_safe.main:main",
        ],
    },
    install_requires=[
        # Add your package dependencies here
    ],
)