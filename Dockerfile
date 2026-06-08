FROM quay.io/jupyter/scipy-notebook:latest

COPY --chown=${NB_UID}:${NB_GID} requirements-dev.txt /tmp/requirements-dev.txt

RUN python -m pip install --no-cache-dir -r /tmp/requirements-dev.txt

# Install Chromium OS-level dependencies as root, then bake in the browser binary
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libatspi2.0-0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2t64 \
    && rm -rf /var/lib/apt/lists/*
USER ${NB_UID}

RUN playwright install chromium

ENV PYTHONPATH=/home/jovyan/work/src
