# Plan: Fix Docker notebook environment

## Goal
Make the Docker Compose Jupyter environment include the project Python
dependencies by default, so notebooks work without manual package installation.

## Slices
- [x] add a project Docker image that installs the repo requirements
- [x] update Compose, setup, README, and agent validation docs to use the project image
- [x] document the environment fix and validation result
