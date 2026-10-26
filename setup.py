from codecs import open

from setuptools import find_packages, setup

REPO_URL = "https://github.com/mandarons/icloudpy"
VERSION = "0.12.0"

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
        "Programming Language :: Python :: 3.14",
        "Operating System :: OS Independent",
    ],
    # 3.14 is the floor: it matches the CI runtime, the devcontainer image and
    # the Ruff target. The runtime deps themselves declare >=3.10, so this
    # is a project support decision, not a dependency constraint.
    python_requires=">=3.14",
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
