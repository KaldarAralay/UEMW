using UnrealBuildTool;
public class UEMorrowindEditorTarget : TargetRules {
    public UEMorrowindEditorTarget(TargetInfo Target) : base(Target) {
        Type=TargetType.Editor; DefaultBuildSettings=BuildSettingsVersion.V2;
        IncludeOrderVersion=EngineIncludeOrderVersion.Unreal5_2;
        WindowsPlatform.CompilerVersion=System.Environment.GetEnvironmentVariable("UEMW_COMPILER_VERSION") ?? "14.34.31933";
        WindowsPlatform.WindowsSdkVersion=System.Environment.GetEnvironmentVariable("UEMW_SDK_VERSION");
        ExtraModuleNames.Add("UEMorrowind");
    }
}
