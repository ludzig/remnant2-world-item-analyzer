# r2wa - Build- und Entwicklungsaufgaben
#
# Entwickelt wird auf Windows, gebaut und ausgefuehrt auf Linux.
# `just sync` spiegelt das Arbeitsverzeichnis auf die Testmaschine;
# Ziel ueber die Umgebungsvariable R2WA_REMOTE setzen, z.B.
#   export R2WA_REMOTE=user@steamdeck:~/dev/r2wa

remote := env_var_or_default("R2WA_REMOTE", "")
parser_out := "build/parser"
parser_bin := parser_out / "r2wa-parser"

default:
    @just --list

# --- Parser (C#) ----------------------------------------------------------

# Baue den Parser fuer Linux als eigenstaendiges Binary (auch von Windows aus).
build-parser:
    dotnet publish parser/R2waParser.csproj -c Release -r linux-x64 \
        --self-contained -p:PublishSingleFile=true -o {{parser_out}}

# Baue den Parser fuer den lokalen Rechner - fuer Tests auf dem Windows-Host.
build-parser-host:
    dotnet publish parser/R2waParser.csproj -c Release -o {{parser_out}}

# --- Python-App -----------------------------------------------------------

# Starte die Anwendung aus dem Arbeitsverzeichnis.
run *args:
    PYTHONPATH=src python3 -m r2wa.main {{args}}

# Zeige die gefundenen Savegame-Verzeichnisse.
discover:
    PYTHONPATH=src python3 -m r2wa.discovery

# Analysiere ein Savegame direkt ueber den Parser und gib das JSON aus.
analyze dir:
    {{parser_bin}} analyze --save-dir "{{dir}}" --pretty

# --- Qualitaet ------------------------------------------------------------

test:
    python3 -m pytest -q

lint:
    python3 -m ruff check src tests
    python3 -m ruff format --check src tests

fmt:
    python3 -m ruff format src tests
    python3 -m ruff check --fix src tests

check: lint test

# --- Fixtures -------------------------------------------------------------

# Erzeuge die erwartete JSON-Ausgabe fuer die Save-Fixtures neu.
# Nur aufrufen, wenn die Abweichung geprueft und gewollt ist.
bless:
    PYTHONPATH=src python3 tests/bless_fixtures.py {{parser_bin}}

# --- Sync -----------------------------------------------------------------

# Spiegle das Arbeitsverzeichnis auf die Linux-Testmaschine.
sync:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -z "{{remote}}" ]; then
        echo "R2WA_REMOTE ist nicht gesetzt, z.B. user@host:~/dev/r2wa" >&2
        exit 1
    fi
    rsync -av --delete \
        --exclude '.git/' --exclude '.venv/' --exclude 'build/' \
        --exclude 'bin/' --exclude 'obj/' --exclude '__pycache__/' \
        ./ "{{remote}}/"

clean:
    rm -rf build parser/bin parser/obj .pytest_cache .ruff_cache
