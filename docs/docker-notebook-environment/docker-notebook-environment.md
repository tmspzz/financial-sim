# Docker Notebook Environment

## What changed
Added a project Docker image named `financial-sim:latest`.

The image is built from:

```text
quay.io/jupyter/scipy-notebook:latest
```

It installs `requirements-dev.txt` at build time and sets:

```text
PYTHONPATH=/home/jovyan/work/src
```

## Why
`docker compose up` previously started the upstream Jupyter image directly. The
one-off quality commands installed dependencies with `pip install -r
requirements-dev.txt`, but the persistent JupyterLab notebook container did not.
That meant notebooks could miss packages such as `pdfplumber`, `pyarrow`,
`requests`, `pytest`, or `ruff`.

The notebook server, scripts, and validation commands now use the same project
image.

## Files affected
- `Dockerfile` — builds `financial-sim:latest` from the Jupyter scipy image.
- `compose.yml` — builds and runs the project image for JupyterLab.
- `setup.sh` — builds the project image and runs quality checks from it.
- `README.md` — documents `docker compose build` and the project image.
- `AGENTS.md` — updates the full quality command.
- `.agents/execution-and-validation.md` — records that Docker must always work
  without manual notebook-time package installs.

## Known limitations
When dependencies change, rebuild the image:

```bash
docker compose build
```

Docker builds may need access to Docker's normal build cache outside the repo.
