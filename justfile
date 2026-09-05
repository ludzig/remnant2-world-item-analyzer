# r2wa - build and development tasks
#
# Developed on Windows, built and run on Linux.
# `just sync` mirrors the working directory to the test machine;
# set the target via the R2WA_REMOTE environment variable, e.g.
#   export R2WA_REMOTE=user@steamdeck:~/dev/r2wa

remote := env_var_or_default("R2WA_REMOTE", "")
parser_out := "build/parser"
parser_bin := parser_out / "r2wa-parser"

default:
    @just --list

# --- Parser (C#) ----------------------------------------------------------

# Build the parser for Linux (also from Windows) and fetch item icons while at it.
build-parser: fetch-icons
    dotnet publish parser/R2waParser.csproj -c Release -r linux-x64 \
        --self-contained -p:PublishSingleFile=true -o {{parser_out}}

# Build the parser for the local machine - for tests on the Windows host.
build-parser-host:
    dotnet publish parser/R2waParser.csproj -c Release -o {{parser_out}}

# --- Python app -------------------------------------------------------------

# Start the application from the working directory.
run *args:
    PYTHONPATH=src python3 -m r2wa.main {{args}}

# Show the save game directories found.
discover:
    PYTHONPATH=src python3 -m r2wa.discovery

# Analyze a save game directly through the parser and print the JSON.
analyze dir:
    {{parser_bin}} analyze --save-dir "{{dir}}" --pretty

# Download all item icons and vendor/boss portraits from the Remnant wiki once (cached in build/icons, skips what's already there).
fetch-icons:
    PYTHONPATH=src python3 -m r2wa.icon_fetch

# --- Quality ----------------------------------------------------------------

test:
    python3 -m pytest -q

# Smoke test of the UI: actually builds the views and checks them.
# Needs PyGObject and a display, so it doesn't run under `just test`.
smoke *args:
    PYTHONPATH=src python3 tests/smoke_ui.py {{args}}

lint:
    python3 -m ruff check src tests
    python3 -m ruff format --check src tests

fmt:
    python3 -m ruff format src tests
    python3 -m ruff check --fix src tests

check: lint test

# --- Fixtures ---------------------------------------------------------------

# Regenerate the expected JSON output for the save fixtures.
# Only run this once the difference has been reviewed and is intentional.
bless:
    PYTHONPATH=src python3 tests/bless_fixtures.py {{parser_bin}}

# --- Sync ---------------------------------------------------------------

# Mirror the working directory to the Linux test machine.
sync:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -z "{{remote}}" ]; then
        echo "R2WA_REMOTE is not set, e.g. user@host:~/dev/r2wa" >&2
        exit 1
    fi
    rsync -av --delete \
        --exclude '.git/' --exclude '.venv/' --exclude 'build/' \
        --exclude 'bin/' --exclude 'obj/' --exclude '__pycache__/' \
        ./ "{{remote}}/"

clean:
    rm -rf build parser/bin parser/obj .pytest_cache .ruff_cache
