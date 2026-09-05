using System.Text.Json.Serialization;

namespace R2wa.Parser.Contract;

/// <summary>
/// Root of the JSON contract between the parser and the GTK application.
/// </summary>
/// <remarks>
/// This is deliberately <em>not</em> the analyzer library's dataset, but its
/// own, versioned view of it. If something changes upstream, the fix stays
/// confined to <see cref="DatasetMapper"/> and the Python side notices
/// nothing.
/// </remarks>
public sealed class AnalysisResult
{
    /// <summary>Must match SCHEMA_VERSION in src/r2wa/__init__.py.</summary>
    public const int CurrentSchemaVersion = 1;

    public int SchemaVersion { get; init; } = CurrentSchemaVersion;
    public required GeneratorInfo Generator { get; init; }
    public required string SaveDir { get; init; }
    public int ActiveCharacterIndex { get; init; }
    public List<string> AccountAwards { get; init; } = [];

    /// <summary>
    /// The immutable master data of every collectible item, listed once.
    /// Characters reference it via <see cref="ItemStateDto.Id"/> instead of
    /// repeating the metadata per character - that saves a multiple of the
    /// payload when analyzing five slots.
    /// </summary>
    public List<CatalogItemDto> Catalog { get; init; } = [];

    public List<CharacterDto> Characters { get; init; } = [];

    /// <summary>
    /// Non-fatal problems during the analysis, e.g. individual items whose
    /// reachability the library could not determine. The application should
    /// be able to display these without the analysis counting as failed.
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
    /// <summary>Machine-readable error class, e.g. <c>save_dir_not_found</c>.</summary>
    public required string Kind { get; init; }
    public required string Message { get; init; }
    public string? Detail { get; init; }
}

public sealed class CharacterDto
{
    /// <summary>Slot number, matches the digit in save_N.sav.</summary>
    public int Index { get; init; }

    public string? Archetype { get; init; }
    public string? SecondaryArchetype { get; init; }
    public string? Gender { get; init; }
    public int PowerLevel { get; init; }
    public int ItemLevel { get; init; }
    public int TraitRank { get; init; }
    public int TraitPoints { get; init; }
    public bool IsHardcore { get; init; }

    /// <summary>Last modification of the save slot, ISO 8601 in UTC.</summary>
    public DateTime SaveDateTime { get; init; }

    /// <summary><c>campaign</c> or <c>adventure</c>.</summary>
    public string ActiveWorldSlot { get; init; } = "campaign";

    public double? PlaytimeSeconds { get; init; }

    public required CountsDto Counts { get; init; }

    /// <summary>
    /// Ownership status per item. Contains one entry for every item in
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
    /// The value reported by the library. It differs slightly from
    /// <see cref="Acquired"/> because other types are counted there too;
    /// kept around to be able to spot deviations in the mapping.
    /// </summary>
    public int AcquiredReported { get; init; }

    /// <summary>Progress per category, keyed by category.</summary>
    public Dictionary<string, CategoryCountDto> ByCategory { get; init; } = [];
}

public sealed class CategoryCountDto
{
    public int Acquired { get; init; }
    public int Total { get; init; }
}

/// <summary>Master data of a collectible item, independent of the character.</summary>
public sealed class CatalogItemDto
{
    public required string Id { get; init; }
    public required string Name { get; init; }

    /// <summary>Category from db.json, e.g. <c>ring</c>, <c>weapon</c>, <c>trait</c>.</summary>
    public required string Category { get; init; }

    /// <summary>Subcategory, e.g. <c>Long Gun</c> or <c>Melee</c>.</summary>
    public string? Subcategory { get; init; }

    public string? World { get; init; }

    /// <summary>Kind of drop location, e.g. <c>Vendor</c> or <c>World Drop</c>.</summary>
    public string? DropType { get; init; }

    /// <summary>Specific drop location, e.g. the vendor's name.</summary>
    public string? DropReference { get; init; }

    /// <summary>Free-text hint from db.json on how to obtain the item.</summary>
    public string? Note { get; init; }

    public string? Prerequisite { get; init; }
    public bool CoopOnly { get; init; }
    public bool AccountAward { get; init; }
}

/// <summary>Ownership status of an item for a particular character.</summary>
public sealed class ItemStateDto
{
    public required string Id { get; init; }
    public bool Acquired { get; init; }

    // --- Only populated for acquired items ---
    public int? Level { get; init; }
    public int? Quantity { get; init; }
    public bool Favorited { get; init; }
    public bool IsEquipped { get; init; }

    /// <summary>
    /// Whether the item is reachable in the currently rolled campaign.
    /// <c>null</c> means unknown - either not checked (because it was
    /// already acquired) or the library couldn't determine it; the latter
    /// then shows up as a note in <see cref="AnalysisResult.Warnings"/>.
    /// </summary>
    public bool? ObtainableInCampaign { get; init; }

    public bool? ObtainableInAdventure { get; init; }
}

public sealed class WorldDto
{
    /// <summary><c>campaign</c> or <c>adventure</c>.</summary>
    public required string Slot { get; init; }
    public string? Difficulty { get; init; }
    public double? PlaytimeSeconds { get; init; }
    public string? RespawnPoint { get; init; }
    public List<ZoneDto> Zones { get; init; } = [];
}

public sealed class ZoneDto
{
    public required string Name { get; init; }

    /// <summary>The zone's rolled story branch, e.g. <c>Empress</c>.</summary>
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

    /// <summary>Kind of drop location, e.g. <c>location</c>, <c>event</c>, <c>vendor</c>.</summary>
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

    /// <summary>Whether the material needed to craft it is available.</summary>
    public bool HasRequiredMaterial { get; init; }

    /// <summary>Whether a prerequisite is missing, i.e. the item is still blocked.</summary>
    public bool IsPrerequisiteMissing { get; init; }

    public bool CoopOnly { get; init; }
}

/// <summary>Output of <c>r2wa-parser catalog</c> - the plain item catalog from db.json.</summary>
public sealed class CatalogResult
{
    public int SchemaVersion { get; init; } = AnalysisResult.CurrentSchemaVersion;
    public required GeneratorInfo Generator { get; init; }
    public List<string> Categories { get; init; } = [];
    public List<CatalogItemDto> Items { get; init; } = [];
}

/// <summary>Output of <c>r2wa-parser version</c>.</summary>
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
