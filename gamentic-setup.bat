@echo off
rem Gamentic setup launcher: host python if present, else the project's required docker.
pushd "%~dp0"
where py >nul 2>nul && (py infra\setup\cli.py %* & goto done)
where python >nul 2>nul && (python infra\setup\cli.py %* & goto done)
docker run -it --rm -v "%cd%":/work -w /work python:3.12-slim python infra/setup/cli.py %*
:done
popd
