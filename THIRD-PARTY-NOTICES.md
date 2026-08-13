# Fremdkomponenten

Diese Anwendung wäre ohne die folgende Vorarbeit nicht möglich. Das
Savegame-Format von Remnant 2 ist Unreal-Engine-basiert und undokumentiert;
die eigentliche Leistung steckt im Parser und in der Item-Datenbank.

## lib.remnant2.analyzer

- Autor: AndrewSav
- Quelle: https://github.com/AndrewSav/lib.remnant2.analyzer
- Lizenz: MIT
- Eingebunden als NuGet-Paket in `parser/R2waParser.csproj`

Liefert die Analyse der Savegames und enthält die eingebettete `db.json` mit
sämtlichen Items des Spiels sowie die Logik, welche davon einem Charakter noch
fehlen.

## lib.remnant2.saves

- Autor: AndrewSav
- Quelle: https://github.com/AndrewSav/lib.remnant2.saves
- Lizenz: MIT
- Transitive Abhängigkeit von `lib.remnant2.analyzer`

Die eigentliche Formatarbeit: Dekompression des Containers, CRC32-Prüfung und
die Unreal-Property-Serialisierung.

## remnant-item-finder

- Autor: t1nky
- Quelle: https://github.com/t1nky/remnant-item-finder

Die ursprüngliche Dokumentation des Dateiformats, auf der die beiden
Bibliotheken oben aufbauen.

## Weitere Abhängigkeiten des Parsers

Transitiv über `lib.remnant2.analyzer` eingebunden:

- Newtonsoft.Json — MIT
- Serilog, SerilogTimings — Apache-2.0

Die vollständigen Lizenztexte liegen den jeweiligen NuGet-Paketen bei und
finden sich in den oben verlinkten Quellen.

## Nicht verwandt

Diese Anwendung ist weder mit Gunfire Games noch mit Gearbox Publishing
verbunden. Remnant II ist eine Marke der jeweiligen Rechteinhaber.
