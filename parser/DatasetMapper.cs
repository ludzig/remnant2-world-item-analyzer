using lib.remnant2.analyzer;
using lib.remnant2.analyzer.Model;
using R2wa.Parser.Contract;

namespace R2wa.Parser;

/// <summary>
/// Uebersetzt das <see cref="Dataset"/> der Analyzer-Bibliothek in den
/// JSON-Vertrag. Dies ist die einzige Klasse, die die Upstream-Typen kennt.
/// </summary>
public static class DatasetMapper
{
    /// <summary>
    /// Item-Kategorien, die fuer eine Sammel-Checkliste zaehlen.
    /// <c>Analyzer.InventoryTypes</c> deckt die Ausruestung ab; Traits fuehrt
    /// die Bibliothek getrennt, gehoeren aus Spielersicht aber dazu.
    /// Nicht enthalten sind Material, Waehrung, Skills und Questgegenstaende -
    /// das sind keine sammelbaren Fundstuecke.
    /// </summary>
    private static readonly HashSet<string> CollectibleTypes =
        [.. Analyzer.InventoryTypes, "trait"];

    public static AnalysisResult Map(Dataset dataset, string saveDir)
    {
        var warnings = new List<string>();

        // Der Katalog kommt aus db.json und ist fuer alle Charaktere gleich.
        // Damit ein Charakter zu jedem Katalogeintrag einen Zustand liefern
        // kann, wird er hier einmal aufgebaut und unten nur noch referenziert.
        var catalog = BuildCatalogItems();
        var catalogIds = catalog.Select(item => item.Id).ToList();

        var characters = new List<CharacterDto>();
        foreach (var character in dataset.Characters)
        {
            try
            {
                characters.Add(MapCharacter(character, catalog, catalogIds, warnings));
            }
            catch (Exception ex)
            {
                // Ein kaputter Slot darf nicht die uebrigen Charaktere kosten.
                warnings.Add($"Slot {character.Index} konnte nicht ausgewertet werden: {ex.Message}");
            }
        }

        return new AnalysisResult
        {
            Generator = BuildInfo.Generator,
            SaveDir = saveDir,
            ActiveCharacterIndex = dataset.ActiveCharacterIndex,
            AccountAwards = [.. dataset.AccountAwards],
            Catalog = catalog,
            Characters = characters,
            Warnings = warnings,
        };
    }

    private static CharacterDto MapCharacter(
        Character character,
        List<CatalogItemDto> catalog,
        List<string> catalogIds,
        List<string> warnings)
    {
        var profile = character.Profile;
        var save = character.Save;
        var states = MapItemStates(character, catalogIds, warnings);

        return new CharacterDto
        {
            Index = character.Index,
            Archetype = Blank(profile.Archetype),
            SecondaryArchetype = Blank(profile.SecondaryArchetype),
            Gender = Blank(profile.Gender),
            PowerLevel = profile.PowerLevel,
            ItemLevel = profile.ItemLevel,
            TraitRank = profile.TraitRank,
            TraitPoints = profile.LastSavedTraitPoints,
            IsHardcore = profile.IsHardcore,
            SaveDateTime = character.SaveDateTime.ToUniversalTime(),
            ActiveWorldSlot = character.ActiveWorldSlot.ToString().ToLowerInvariant(),
            PlaytimeSeconds = save?.Playtime?.TotalSeconds,
            Counts = BuildCounts(catalog, states, profile.AcquiredItems),
            ItemStates = states,
            Worlds = MapWorlds(save),
        };
    }

    /// <summary>
    /// Bestimmt fuer jeden Katalogeintrag, ob der Charakter ihn besitzt.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Das Inventar der Bibliothek enthaelt auch Nicht-Sammelobjekte wie
    /// Material oder Waehrung; massgeblich ist deshalb der Katalog, nicht das
    /// Inventar. Was im Inventar steht, aber nicht im Katalog, ist bewusst
    /// nicht Teil der Checkliste.
    /// </para>
    /// <para>
    /// Ein Inventareintrag allein bedeutet noch keinen Besitz: aufgebrauchte
    /// Verbrauchsgegenstaende und Gebraeue bleiben mit <c>Quantity == 0</c>
    /// stehen. Genau diese fuehrt die Bibliothek parallel unter MissingItems.
    /// Die Regel "im Inventar und Menge ungleich 0" reproduziert deren
    /// FilteredInventory ueber alle geprueften Slots exakt.
    /// </para>
    /// </remarks>
    private static List<ItemStateDto> MapItemStates(
        Character character, List<string> catalogIds, List<string> warnings)
    {
        var owned = new Dictionary<string, InventoryItem>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in character.Profile.Inventory)
        {
            var loot = entry.LootItem;
            if (loot is null || entry.Quantity == 0) continue;
            owned.TryAdd(loot.Id, entry);
        }

        var states = new List<ItemStateDto>(catalogIds.Count);
        foreach (var id in catalogIds)
        {
            if (owned.TryGetValue(id, out var entry))
            {
                states.Add(new ItemStateDto
                {
                    Id = id,
                    Acquired = true,
                    Level = entry.Level,
                    Quantity = entry.Quantity,
                    Favorited = entry.Favorited,
                    IsEquipped = entry.IsEquipped,
                });
                continue;
            }

            var (campaign, adventure) = Obtainable(character, id, warnings);
            states.Add(new ItemStateDto
            {
                Id = id,
                Acquired = false,
                ObtainableInCampaign = campaign,
                ObtainableInAdventure = adventure,
            });
        }

        return states;
    }

    /// <summary>
    /// Ermittelt, ob ein fehlendes Item in den aktuell gerollten Welten
    /// erreichbar ist.
    /// </summary>
    /// <remarks>
    /// <c>RolledWorld.CanGetItem</c> wirft bei einzelnen Items mit
    /// Voraussetzungen eine InvalidOperationException (Fehler in
    /// CheckPrerequisites stromaufwaerts, beobachtet bei
    /// Amulet_OneTrueKingSigil). Das darf die Analyse nicht abbrechen -
    /// solche Items werden als "unbekannt" gefuehrt und gemeldet.
    /// </remarks>
    private static (bool? Campaign, bool? Adventure) Obtainable(
        Character character, string id, List<string> warnings)
    {
        return (Check(character.Save?.Campaign, "Kampagne"),
                Check(character.Save?.Adventure, "Abenteuer"));

        bool? Check(RolledWorld? world, string label)
        {
            if (world is null) return null;
            try
            {
                return world.CanGetItem(id);
            }
            catch (Exception ex)
            {
                warnings.Add(
                    $"Slot {character.Index}: Erreichbarkeit von '{id}' in der {label} " +
                    $"nicht bestimmbar ({ex.GetType().Name}).");
                return null;
            }
        }
    }

    private static CountsDto BuildCounts(
        List<CatalogItemDto> catalog, List<ItemStateDto> states, int acquiredReported)
    {
        var acquiredIds = states.Where(s => s.Acquired)
                                .Select(s => s.Id)
                                .ToHashSet(StringComparer.OrdinalIgnoreCase);

        var byCategory = catalog
            .GroupBy(item => item.Category)
            .ToDictionary(
                group => group.Key,
                group => new CategoryCountDto
                {
                    Acquired = group.Count(item => acquiredIds.Contains(item.Id)),
                    Total = group.Count(),
                });

        return new CountsDto
        {
            Acquired = acquiredIds.Count,
            Missing = catalog.Count - acquiredIds.Count,
            Total = catalog.Count,
            AcquiredReported = acquiredReported,
            ByCategory = byCategory,
        };
    }

    private static List<WorldDto> MapWorlds(SaveSlot? save)
    {
        if (save is null) return [];

        var worlds = new List<WorldDto>();
        if (save.Campaign is not null) worlds.Add(MapWorld(save.Campaign, "campaign"));
        if (save.Adventure is not null) worlds.Add(MapWorld(save.Adventure, "adventure"));
        return worlds;
    }

    private static WorldDto MapWorld(RolledWorld world, string slot) => new()
    {
        Slot = slot,
        Difficulty = Blank(world.Difficulty),
        PlaytimeSeconds = world.Playtime?.TotalSeconds,
        RespawnPoint = Blank(world.RespawnPoint?.Name),
        // AllZones enthaelt zusaetzlich Ward 13, das nicht in Zones steht.
        Zones = [.. world.AllZones.Select(MapZone)],
    };

    private static ZoneDto MapZone(Zone zone) => new()
    {
        Name = zone.Name,
        Story = Blank(zone.Story),
        Finished = zone.Finished,
        CompletesBiome = zone.CompletesBiome,
        Locations = [.. zone.Locations.Select(MapLocation)],
    };

    private static LocationDto MapLocation(Location location) => new()
    {
        Name = location.Name,
        Category = Blank(location.Category),
        World = Blank(location.World),
        WorldStones = [.. location.WorldStones],
        Connections = [.. location.Connections],
        Vendors = [.. location.Vendors],
        TraitBook = location.TraitBook,
        TraitBookLooted = location.TraitBookLooted,
        Simulacrum = location.Simulacrum,
        SimulacrumLooted = location.SimulacrumLooted,
        Bloodmoon = location.Bloodmoon,
        LootGroups = [.. location.LootGroups.Select(MapLootGroup)],
    };

    private static LootGroupDto MapLootGroup(LootGroup group) => new()
    {
        Name = Blank(group.Name),
        Type = Blank(group.Type),
        EventDropReference = Blank(group.EventDropReference),
        Items = [.. group.Items.Select(MapLootItem)],
    };

    private static LootItemDto MapLootItem(LootItemExtended item) => new()
    {
        Id = item.Id,
        Name = Blank(item.Name) ?? item.Id,
        Category = item.Type,
        Subcategory = Blank(item.Properties.GetValueOrDefault("Subtype")),
        IsLooted = item.IsLooted,
        HasRequiredMaterial = item.HasRequiredMaterial,
        IsPrerequisiteMissing = item.IsPrerequisiteMissing,
        CoopOnly = IsTrue(item.Properties.GetValueOrDefault("Coop")),
    };

    /// <summary>Ausgabe fuer <c>r2wa-parser catalog</c> - Katalog ohne Savegame.</summary>
    public static CatalogResult BuildCatalog() => new()
    {
        Generator = BuildInfo.Generator,
        Categories = [.. CollectibleTypes.Order(StringComparer.Ordinal)],
        Items = BuildCatalogItems(),
    };

    /// <summary>
    /// Liest alle sammelbaren Items aus db.json, sortiert nach Kategorie und
    /// Name. Die Reihenfolge ist stabil, damit sich Fixture-Vergleiche nicht
    /// grundlos aendern.
    /// </summary>
    private static List<CatalogItemDto> BuildCatalogItems()
    {
        var items = new List<CatalogItemDto>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var row in ItemDb.Db)
        {
            var id = row.GetValueOrDefault("Id");
            var type = row.GetValueOrDefault("Type");
            if (string.IsNullOrEmpty(id) || type is null) continue;
            if (!CollectibleTypes.Contains(type) || !seen.Add(id)) continue;

            items.Add(new CatalogItemDto
            {
                Id = id,
                // Nicht jeder db.json-Eintrag hat einen Anzeigenamen; dann ist
                // die technische Id immer noch besser als eine leere Zeile.
                Name = Blank(row.GetValueOrDefault("Name")) ?? id,
                Category = type,
                Subcategory = Blank(row.GetValueOrDefault("Subtype")),
                World = Blank(row.GetValueOrDefault("World")),
                DropType = Blank(row.GetValueOrDefault("DropType")),
                DropReference = Blank(row.GetValueOrDefault("DropReference")),
                Note = Blank(row.GetValueOrDefault("Note")),
                Prerequisite = Blank(row.GetValueOrDefault("Prerequisite")),
                CoopOnly = IsTrue(row.GetValueOrDefault("Coop")),
                AccountAward = IsTrue(row.GetValueOrDefault("AccountAward")),
            });
        }

        items.Sort(static (a, b) =>
        {
            var byCategory = string.CompareOrdinal(a.Category, b.Category);
            if (byCategory != 0) return byCategory;
            var byName = string.CompareOrdinal(a.Name, b.Name);
            return byName != 0 ? byName : string.CompareOrdinal(a.Id, b.Id);
        });

        return items;
    }

    /// <summary>Leere und nur aus Leerzeichen bestehende Werte werden zu null.</summary>
    private static string? Blank(string? value) =>
        string.IsNullOrWhiteSpace(value) ? null : value;

    private static bool IsTrue(string? value) =>
        string.Equals(value, "True", StringComparison.OrdinalIgnoreCase);
}
