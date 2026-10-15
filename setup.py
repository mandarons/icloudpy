from codecs import open

from setuptools import find_packages, setup

REPO_URL = "https://github.com/mandarons/icloudpy"
VERSION = "0.10.0"

with open("README.md") as fh:
    long_description = fh.read()
with open("requirements.txt") as fh:
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
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.10",
        "Operating System :: OS Independent",
    ],
    # 3.10 is the floor: the pinned runtime deps require it (requests 2.34,
    # click 8.5 and tzlocal 5.4 all declare >=3.10), it matches the CI/badge,
    # and pyupgrade enforces the same level.
    python_requires=">=3.10",
    install_requires=required,
    extras_require={
        # Optional: only needed to sign a security-key (WebAuthn) challenge locally.
        "security-key": ["fido2"],
    },
    entry_points="""
    [console_scripts]
    icloud=icloudpy.cmdline:main
    """,
)
