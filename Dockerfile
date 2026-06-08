FROM quay.io/jupyter/scipy-notebook:latest

COPY --chown=${NB_UID}:${NB_GID} requirements-dev.txt /tmp/requirements-dev.txt

RUN python -m pip install --no-cache-dir -r /tmp/requirements-dev.txt

ENV PYTHONPATH=/home/jovyan/work/src
