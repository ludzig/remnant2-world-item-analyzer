using System.Text.Json.Serialization;

namespace R2wa.Parser.Contract;

/// <summary>
/// Wurzel des JSON-Vertrags zwischen Parser und GTK-Anwendung.
/// </summary>
/// <remarks>
/// Dies ist bewusst <em>nicht</em> das Dataset der Analyzer-Bibliothek, sondern
/// eine eigene, versionierte Sicht darauf. Aendert sich stromaufwaerts etwas,
/// bleibt die Anpassung auf <see cref="DatasetMapper"/> beschraenkt und die
/// Python-Seite merkt nichts davon.
/// </remarks>
public sealed class AnalysisResult
{
    /// <summary>Muss zu SCHEMA_VERSION in src/r2wa/__init__.py passen.</summary>
    public const int CurrentSchemaVersion = 1;

    public int SchemaVersion { get; init; } = CurrentSchemaVersion;
    public required GeneratorInfo Generator { get; init; }
    public required string SaveDir { get; init; }
    public int ActiveCharacterIndex { get; init; }
    public List<string> AccountAwards { get; init; } = [];

    /// <summary>
    /// Die unveraenderlichen Stammdaten aller sammelbaren Items, einmalig.
    /// Charaktere verweisen ueber <see cref="ItemStateDto.Id"/> hierauf, statt
    /// die Metadaten je Charakter zu wiederholen - das spart beim Analysieren
    /// von fuenf Slots ein Vielfaches an Nutzlast.
    /// </summary>
    public List<CatalogItemDto> Catalog { get; init; } = [];

    public List<CharacterDto> Characters { get; init; } = [];

    /// <summary>
    /// Nicht-fatale Probleme waehrend der Analyse, etwa einzelne Items, deren
    /// Erreichbarkeit die Bibliothek nicht bestimmen konnte. Die Anwendung soll
    /// das anzeigen koennen, ohne dass die Analyse als gescheitert gilt.
    /// </summary>
    public List<string> Warnings { get; init; } = [];
}

public sealed class GeneratorInfo
{
    public required string Parser { get; init; }
    public required string Analyzer { get; init; }
}

public sealed class ErrorResult
{
    public int SchemaVersion { get; init; } = AnalysisResult.CurrentSchemaVersion;
    public required ErrorInfo Error { get; init; }
}

public sealed class ErrorInfo
{
    /// <summary>Maschinenlesbare Fehlerklasse, z.B. <c>save_dir_not_found</c>.</summary>
    public required string Kind { get; init; }
    public required string Message { get; init; }
    public string? Detail { get; init; }
}

public sealed class CharacterDto
{
    /// <summary>Slot-Nummer, entspricht der Ziffer in save_N.sav.</summary>
    public int Index { get; init; }

    public string? Archetype { get; init; }
    public string? SecondaryArchetype { get; init; }
    public string? Gender { get; init; }
    public int PowerLevel { get; init; }
    public int ItemLevel { get; init; }
    public int TraitRank { get; init; }
    public int TraitPoints { get; init; }
    public bool IsHardcore { get; init; }

    /// <summary>Letzte Aenderung des Save-Slots, ISO 8601 in UTC.</summary>
    public DateTime SaveDateTime { get; init; }

    /// <summary><c>campaign</c> oder <c>adventure</c>.</summary>
    public string ActiveWorldSlot { get; init; } = "campaign";

    public double? PlaytimeSeconds { get; init; }

    public required CountsDto Counts { get; init; }

    /// <summary>
    /// Besitzstand je Item. Enthaelt einen Eintrag fuer jedes Item aus
    /// <see cref="AnalysisResult.Catalog"/>.
    /// </summary>
    public List<ItemStateDto> ItemStates { get; init; } = [];

    public List<WorldDto> Worlds { get; init; } = [];
}

public sealed class CountsDto
{
    public int Acquired { get; init; }
    public int Missing { get; init; }
    public int Total { get; init; }

    /// <summary>
    /// Der von der Bibliothek gemeldete Wert. Er weicht leicht von
    /// <see cref="Acquired"/> ab, weil dort andere Typen mitgezaehlt werden;
    /// mitgefuehrt, um Abweichungen im Mapping erkennen zu koennen.
    /// </summary>
    public int AcquiredReported { get; init; }

    /// <summary>Fortschritt je Kategorie, Schluessel ist die Kategorie.</summary>
    public Dictionary<string, CategoryCountDto> ByCategory { get; init; } = [];
}

public sealed class CategoryCountDto
{
    public int Acquired { get; init; }
    public int Total { get; init; }
}

/// <summary>Stammdaten eines sammelbaren Items, unabhaengig vom Charakter.</summary>
public sealed class CatalogItemDto
{
    public required string Id { get; init; }
    public required string Name { get; init; }

    /// <summary>Kategorie aus db.json, z.B. <c>ring</c>, <c>weapon</c>, <c>trait</c>.</summary>
    public required string Category { get; init; }

    /// <summary>Unterkategorie, z.B. <c>Long Gun</c> oder <c>Melee</c>.</summary>
    public string? Subcategory { get; init; }

    public string? World { get; init; }

    /// <summary>Art der Fundstelle, z.B. <c>Vendor</c> oder <c>World Drop</c>.</summary>
    public string? DropType { get; init; }

    /// <summary>Konkrete Fundstelle, z.B. der Haendlername.</summary>
    public string? DropReference { get; init; }

    /// <summary>Freitexthinweis aus db.json, wie man das Item bekommt.</summary>
    public string? Note { get; init; }

    public string? Prerequisite { get; init; }
    public bool CoopOnly { get; init; }
    public bool AccountAward { get; init; }
}

/// <summary>Besitzstand eines Items bei einem bestimmten Charakter.</summary>
public sealed class ItemStateDto
{
    public required string Id { get; init; }
    public bool Acquired { get; init; }

    // --- Nur bei erworbenen Items belegt ---
    public int? Level { get; init; }
    public int? Quantity { get; init; }
    public bool Favorited { get; init; }
    public bool IsEquipped { get; init; }

    /// <summary>
    /// Ob das Item in der aktuell gerollten Kampagne erreichbar ist.
    /// <c>null</c> bedeutet unbekannt - entweder nicht geprueft (weil bereits
    /// erworben) oder die Bibliothek konnte es nicht bestimmen; letzteres
    /// steht dann als Hinweis in <see cref="AnalysisResult.Warnings"/>.
    /// </summary>
    public bool? ObtainableInCampaign { get; init; }

    public bool? ObtainableInAdventure { get; init; }
}

public sealed class WorldDto
{
    /// <summary><c>campaign</c> oder <c>adventure</c>.</summary>
    public required string Slot { get; init; }
    public string? Difficulty { get; init; }
    public double? PlaytimeSeconds { get; init; }
    public string? RespawnPoint { get; init; }
    public List<ZoneDto> Zones { get; init; } = [];
}

public sealed class ZoneDto
{
    public required string Name { get; init; }

    /// <summary>Der gerollte Story-Strang der Zone, z.B. <c>Empress</c>.</summary>
    public string? Story { get; init; }

    public bool Finished { get; init; }
    public bool CompletesBiome { get; init; }
    public List<LocationDto> Locations { get; init; } = [];
}

public sealed class LocationDto
{
    public required string Name { get; init; }
    public string? Category { get; init; }
    public string? World { get; init; }
    public List<string> WorldStones { get; init; } = [];
    public List<string> Connections { get; init; } = [];
    public List<string> Vendors { get; init; } = [];
    public bool TraitBook { get; init; }
    public bool TraitBookLooted { get; init; }
    public bool Simulacrum { get; init; }
    public bool SimulacrumLooted { get; init; }
    public bool Bloodmoon { get; init; }
    public List<LootGroupDto> LootGroups { get; init; } = [];
}

public sealed class LootGroupDto
{
    public string? Name { get; init; }

    /// <summary>Art der Fundstelle, z.B. <c>location</c>, <c>event</c>, <c>vendor</c>.</summary>
    public string? Type { get; init; }

    public string? EventDropReference { get; init; }
    public List<LootItemDto> Items { get; init; } = [];
}

public sealed class LootItemDto
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public required string Category { get; init; }
    public string? Subcategory { get; init; }
    public bool IsLooted { get; init; }

    /// <summary>Ob das zum Herstellen noetige Material vorhanden ist.</summary>
    public bool HasRequiredMaterial { get; init; }

    /// <summary>Ob eine Voraussetzung fehlt, das Item also noch blockiert ist.</summary>
    public bool IsPrerequisiteMissing { get; init; }

    public bool CoopOnly { get; init; }
}

/// <summary>Ausgabe von <c>r2wa-parser catalog</c> - der reine Item-Katalog aus db.json.</summary>
public sealed class CatalogResult
{
    public int SchemaVersion { get; init; } = AnalysisResult.CurrentSchemaVersion;
    public required GeneratorInfo Generator { get; init; }
    public List<string> Categories { get; init; } = [];
    public List<CatalogItemDto> Items { get; init; } = [];
}

/// <summary>Ausgabe von <c>r2wa-parser version</c>.</summary>
public sealed class VersionResult
{
    public int SchemaVersion { get; init; } = AnalysisResult.CurrentSchemaVersion;
    public required GeneratorInfo Generator { get; init; }
}

[JsonSourceGenerationOptions(
    PropertyNamingPolicy = JsonKnownNamingPolicy.SnakeCaseLower,
    DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull)]
[JsonSerializable(typeof(AnalysisResult))]
[JsonSerializable(typeof(ErrorResult))]
[JsonSerializable(typeof(CatalogResult))]
[JsonSerializable(typeof(VersionResult))]
internal sealed partial class ContractJsonContext : JsonSerializerContext;
