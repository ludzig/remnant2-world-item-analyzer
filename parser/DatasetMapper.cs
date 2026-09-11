using lib.remnant2.analyzer;
using lib.remnant2.analyzer.Model;
using R2wa.Parser.Contract;

namespace R2wa.Parser;

/// <summary>
/// Translates the analyzer library's <see cref="Dataset"/> into the JSON
/// contract. This is the only class that knows about the upstream types.
/// </summary>
public static class DatasetMapper
{
    /// <summary>
    /// Item categories that count for a collection checklist.
    /// <c>Analyzer.InventoryTypes</c> covers equipment; the library keeps
    /// traits separate, but from a player's perspective they belong here too.
    /// Not included: material, currency, skills, and quest items - those
    /// aren't collectible finds.
    /// </summary>
    private static readonly HashSet<string> CollectibleTypes =
        [.. Analyzer.InventoryTypes, "trait"];

    public static AnalysisResult Map(Dataset dataset, string saveDir)
    {
        var warnings = new List<string>();

        // The catalog comes from db.json and is the same for every character.
        // So a character can deliver a state for every catalog entry, it's
        // built once here and only referenced below.
        var catalog = BuildCatalogItems();
        var catalogIds = catalog.Select(item => item.Id).ToList();

        var characters = new List<CharacterDto>();
        foreach (var character in dataset.Characters)
        {
            try
            {
                characters.Add(MapCharacter(character, catalog, catalogIds));
            }
            catch (Exception ex)
            {
                // A broken slot must not cost us the remaining characters.
                warnings.Add($"Slot {character.Index} could not be evaluated: {ex.Message}");
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
        List<string> catalogIds)
    {
        var profile = character.Profile;
        var save = character.Save;
        var states = MapItemStates(character, catalogIds);

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
    /// Determines, for every catalog entry, whether the character owns it.
    /// </summary>
    /// <remarks>
    /// <para>
    /// The library's inventory also contains non-collectible objects such as
    /// material or currency; the catalog is therefore authoritative, not the
    /// inventory. Anything that's in the inventory but not in the catalog is
    /// deliberately not part of the checklist.
    /// </para>
    /// <para>
    /// An inventory entry alone doesn't mean ownership: consumed
    /// consumables and concoctions stay listed with <c>Quantity == 0</c>.
    /// The library tracks exactly these in parallel under MissingItems. The
    /// rule "in the inventory and quantity not zero" reproduces its
    /// FilteredInventory exactly across every slot checked.
    /// </para>
    /// </remarks>
    private static List<ItemStateDto> MapItemStates(
        Character character, List<string> catalogIds)
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

            var (campaign, adventure) = Obtainable(character, id);
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
    /// Determines whether a missing item is reachable in the currently
    /// rolled worlds.
    /// </summary>
    /// <remarks>
    /// <c>RolledWorld.CanGetItem</c> throws for items whose prerequisite the
    /// analyzer cannot resolve in the rolled world:
    /// <c>CheckPrerequisites</c> looks the prerequisite up with
    /// <c>Single()</c> and has nothing to match. Observed for
    /// <c>Amulet_OneTrueKingSigil</c>, whose two prerequisites are the
    /// sigils of Faelin and Faerin - the two bosses of Losomn that never
    /// both appear in one roll.
    ///
    /// This must not abort the analysis. <c>null</c> is returned, which is
    /// the same "we do not know" the caller already uses for a slot with no
    /// rolled world, and the item list shows it as such. Deliberately not a
    /// warning: it says nothing about the save game and there is nothing
    /// the player could do about it, so a banner on every load would be
    /// noise.
    /// </remarks>
    private static (bool? Campaign, bool? Adventure) Obtainable(Character character, string id)
    {
        return (Check(character.Save?.Campaign),
                Check(character.Save?.Adventure));

        bool? Check(RolledWorld? world)
        {
            if (world is null) return null;
            try
            {
                return world.CanGetItem(id);
            }
            catch (InvalidOperationException)
            {
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
        // AllZones additionally includes Ward 13, which isn't in Zones.
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

    /// <summary>Output for <c>r2wa-parser catalog</c> - catalog without a save game.</summary>
    public static CatalogResult BuildCatalog() => new()
    {
        Generator = BuildInfo.Generator,
        Categories = [.. CollectibleTypes.Order(StringComparer.Ordinal)],
        Items = BuildCatalogItems(),
    };

    /// <summary>
    /// Reads every collectible item from db.json, sorted by category and
    /// name. The order is stable so fixture comparisons don't change without
    /// reason.
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
                // Not every db.json entry has a display name; in that case
                // the technical id still beats an empty row.
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

    /// <summary>Empty and whitespace-only values become null.</summary>
    private static string? Blank(string? value) =>
        string.IsNullOrWhiteSpace(value) ? null : value;

    private static bool IsTrue(string? value) =>
        string.Equals(value, "True", StringComparison.OrdinalIgnoreCase);
}
