FROM mcr.microsoft.com/devcontainers/python:0-3.10

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN \
    apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    git \
    cmake \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src

WORKDIR /workspaces

# Install Python dependencies from requirements
COPY requirements*.txt ./
RUN pip install -r requirements-test.txt

# Set the default shell to bash instead of sh
ENV SHELL /bin/bash
