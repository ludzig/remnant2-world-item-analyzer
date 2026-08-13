using System.Text.Json;
using lib.remnant2.analyzer;
using R2wa.Parser.Contract;

namespace R2wa.Parser;

/// <summary>Versionsangaben, die in jede Ausgabe eingebettet werden.</summary>
internal static class BuildInfo
{
    public static GeneratorInfo Generator { get; } = new()
    {
        Parser = typeof(BuildInfo).Assembly.GetName().Version?.ToString(3) ?? "0.0.0",
        Analyzer = typeof(Analyzer).Assembly.GetName().Version?.ToString(3) ?? "unknown",
    };
}

internal static class JsonOutput
{
    public static readonly JsonSerializerOptions Compact =
        new(ContractJsonContext.Default.Options);

    public static readonly JsonSerializerOptions Pretty =
        new(ContractJsonContext.Default.Options) { WriteIndented = true };
}
