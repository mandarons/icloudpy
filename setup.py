from setuptools import setup, find_packages
from codecs import open

REPO_URL = "https://github.com/mandarons/icloudpy"
VERSION = "0.2.1"

with open("README.md", "r") as fh:
    long_description = fh.read()
with open("requirements.txt", "r") as fh:
    required = fh.read().splitlines()

setup(
    name="icloudpy",
    version=VERSION,
    author="Mandar Patil",
    author_email="mandarons@pm.me",
    description="Python library to interact with iCloud web service",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url=REPO_URL,
    package_dir={".": ""},
    packages=find_packages(exclude=["tests"]),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=required,
    entry_points="""
    [console_scripts]
    icloud=icloudpy.cmdline:main
    """,
)
