from codecs import open

from setuptools import find_packages, setup

REPO_URL = "https://github.com/leafnsand/icloudpy"
VERSION = "0.0.1"

with open("README.md") as fh:
    long_description = fh.read()
with open("requirements.txt") as fh:
    required = fh.read().splitlines()

setup(
    name="lns-icloudpy",
    version=VERSION,
    author="leafnsand",
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
