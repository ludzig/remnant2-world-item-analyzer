using System.Text;
using System.Text.Json;
using lib.remnant2.analyzer;
using lib.remnant2.analyzer.Model;
using R2wa.Parser;
using R2wa.Parser.Contract;

// r2wa-parser - bridge between the analyzer library and the GTK application.
//
// stdout carries nothing but JSON, so the calling side can parse it without
// pre-filtering. Everything else - library logs, diagnostics, help text -
// goes to stderr.

Console.OutputEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);

try
{
    return Run(args);
}
catch (Exception ex)
{
    return Fail("unexpected_error", "Unexpected error during analysis.", ex.ToString());
}

static int Run(string[] args)
{
    if (args.Length == 0 || args[0] is "-h" or "--help" or "help")
    {
        Usage();
        return args.Length == 0 ? 2 : 0;
    }

    var pretty = args.Contains("--pretty");

    return args[0] switch
    {
        "version" => Emit(new VersionResult { Generator = BuildInfo.Generator }, pretty),
        "catalog" => Emit(DatasetMapper.BuildCatalog(), pretty),
        "analyze" => Analyze(args, pretty),
        _ => Fail("unknown_command", $"Unknown command '{args[0]}'."),
    };
}

static int Analyze(string[] args, bool pretty)
{
    var saveDir = GetOption(args, "--save-dir");
    if (string.IsNullOrWhiteSpace(saveDir))
        return Fail("missing_argument", "--save-dir is missing.");

    saveDir = Path.GetFullPath(saveDir);

    if (!Directory.Exists(saveDir))
        return Fail("save_dir_not_found", $"Directory not found: {saveDir}");

    if (!File.Exists(Path.Combine(saveDir, "profile.sav")))
        return Fail("profile_not_found", $"No profile.sav in {saveDir}");

    Dataset dataset;
    try
    {
        dataset = Analyzer.Analyze(saveDir);
    }
    catch (Exception ex)
    {
        return Fail("analysis_failed",
            $"Could not read save game: {ex.Message}", ex.ToString());
    }

    return Emit(DatasetMapper.Map(dataset, saveDir), pretty);
}

static int Emit<T>(T value, bool pretty)
{
    var options = pretty ? JsonOutput.Pretty : JsonOutput.Compact;
    Console.Out.Write(JsonSerializer.Serialize(value, typeof(T)!, options));
    Console.Out.Write('\n');
    Console.Out.Flush();
    return 0;
}

static int Fail(string kind, string message, string? detail = null)
{
    var payload = new ErrorResult
    {
        Error = new ErrorInfo { Kind = kind, Message = message, Detail = detail },
    };
    Console.Out.Write(JsonSerializer.Serialize(payload, typeof(ErrorResult), JsonOutput.Compact));
    Console.Out.Write('\n');
    Console.Out.Flush();
    return 1;
}

static string? GetOption(string[] args, string name)
{
    for (var i = 0; i < args.Length - 1; i++)
        if (args[i] == name)
            return args[i + 1];
    return null;
}

static void Usage()
{
    Console.Error.WriteLine("""
        r2wa-parser - reads Remnant 2 save games and prints JSON on stdout.

          analyze --save-dir <path> [--pretty]   analyze a save game directory
          catalog [--pretty]                     item catalog from db.json, no save game needed
          version [--pretty]                     schema and library version

        Exit code 0 on success, otherwise 1; on failure an
        {"error":{...}} object is printed on stdout.
        """);
}
