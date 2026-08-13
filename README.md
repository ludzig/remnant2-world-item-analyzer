# r2wa — Remnant 2 World & Item Analyzer

Eine GNOME-Anwendung, die Remnant-2-Savegames **ausschließlich liest** und
anzeigt, welche Items ein Charakter gefunden hat und welche ihm noch fehlen —
dazu die aktuell gerollten Welten mit Zonen, Orten und Fundstellen.

Kein Backup, kein Speichern, kein Eingriff ins Savegame.

## Aufbau

Der Savegame-Parser existiert nur als C#-Bibliothek. Statt ihn nachzubauen
wird er als schlanker Subprozess eingebunden:

```
┌──────────────────────────────────────────┐
│ r2wa  —  Python + GTK4 / libadwaita      │
│   ├ discovery.py    Proton-Prefix finden │
│   ├ parser_bridge   Subprozess + JSON    │
│   ├ models.py       reine Dataclasses    │
│   └ views/          Items · Welten       │
└─────────────────┬────────────────────────┘
                  │ JSON auf stdout (Schema v1)
┌─────────────────▼────────────────────────┐
│ r2wa-parser  —  C# .NET 10               │
│   └ lib.remnant2.analyzer (MIT)          │
│       └ db.json — alle 849 Items         │
└──────────────────────────────────────────┘
```

Der Parser gibt **nicht** das Datenmodell der Bibliothek roh aus, sondern ein
eigenes, versioniertes Schema. Ändert sich stromaufwärts etwas, bleibt die
Anpassung auf `parser/DatasetMapper.cs` beschränkt.

## Voraussetzungen

- GNOME 46 oder neuer (GTK 4.12+, libadwaita 1.5+)
- Python 3.11+ mit PyGObject — unter Fedora `python3-gobject`,
  unter Debian/Ubuntu `python3-gi python3-gi-cairo gir1.2-adw-1`
- .NET SDK 10 zum Bauen des Parsers
- [just](https://github.com/casey/just) für die Buildaufgaben (optional)

## Loslegen

```bash
just build-parser     # baut build/parser/r2wa-parser für linux-x64
just run              # startet die Anwendung
```

Ohne `just`:

```bash
dotnet publish parser/R2waParser.csproj -c Release -r linux-x64 \
    --self-contained -p:PublishSingleFile=true -o build/parser
PYTHONPATH=src python3 -m r2wa.main
```

Das Savegame wird automatisch gesucht. Ein abweichender Pfad lässt sich als
Argument übergeben oder im Fenster über *Ordner öffnen…* wählen:

```bash
PYTHONPATH=src python3 -m r2wa.main ~/pfad/zum/savegame
```

### Wo die Savegames liegen

Unter Linux im Proton-Prefix des Spiels (App-ID 1282100):

```
~/.steam/steam/steamapps/compatdata/1282100/pfx/drive_c/users/steamuser/
    Saved Games/Remnant2/Steam/<steam-id>/
```

`discovery.py` sucht zusätzlich in `~/.local/share/Steam`, in der
Flatpak-Installation von Steam und in allen Bibliotheken aus
`libraryfolders.vdf`. Was gefunden wurde, zeigt:

```bash
just discover
```

## Entwicklung

Entwickelt wird unter Windows, gebaut und getestet auf einer Linux-Maschine:

```bash
export R2WA_REMOTE=benutzer@rechner:~/dev/r2wa
just sync
```

Der C#-Teil ist auch unter Windows baubar und für `linux-x64`
cross-publishbar; die GTK-Oberfläche braucht Linux.

```bash
just test     # pytest
just lint     # ruff
just check    # beides
```

Die Datenschicht (`models.py`, `parser_bridge.py`, `discovery.py`) kommt ohne
PyGObject aus und ist deshalb auf jeder Plattform testbar. Für den
Integrationstest gegen ein echtes Savegame:

```bash
R2WA_TEST_SAVE_DIR=/pfad/zum/savegame just test
```

### Nützliche Umgebungsvariablen

| Variable | Wirkung |
|---|---|
| `R2WA_PARSER` | Pfad zum Parser-Binary, überschreibt die Suche |
| `R2WA_SAVE_DIR` | Zusätzliche Savegame-Pfade für `just discover` |
| `R2WA_TEST_SAVE_DIR` | Aktiviert den Integrationstest |

### Der Parser als eigenständiges Werkzeug

```bash
build/parser/r2wa-parser analyze --save-dir <pfad> --pretty
build/parser/r2wa-parser catalog --pretty    # Item-Katalog ohne Savegame
build/parser/r2wa-parser version
```

Auf stdout liegt ausschließlich JSON. Im Fehlerfall ein
`{"error":{"kind":…,"message":…}}` mit Exit-Code 1.

## Lizenz

MIT — siehe [LICENSE](LICENSE). Zu den eingebundenen Fremdkomponenten siehe
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
