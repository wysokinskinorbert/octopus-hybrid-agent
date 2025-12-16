from setuptools import setup, find_packages

setup(
    name="octopus-framework",
    version="4.0.0",
    packages=find_packages(),
    install_requires=[
        "typer",
        "rich",
        "litellm",
        "pyyaml",
        "httpx>=0.25.0",
        "textual>=0.40.0",
    ],
    entry_points={
        "console_scripts": [
            "octopus=octopus.main:app",
        ],
    },
)
