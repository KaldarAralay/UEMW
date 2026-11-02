using UnrealBuildTool;
public class UEMorrowindTarget : TargetRules {
    public UEMorrowindTarget(TargetInfo Target) : base(Target) {
        Type=TargetType.Game; DefaultBuildSettings=BuildSettingsVersion.V2;
        IncludeOrderVersion=EngineIncludeOrderVersion.Unreal5_2;
        WindowsPlatform.CompilerVersion=System.Environment.GetEnvironmentVariable("UEMW_COMPILER_VERSION") ?? "14.34.31933";
        WindowsPlatform.WindowsSdkVersion=System.Environment.GetEnvironmentVariable("UEMW_SDK_VERSION");
        ExtraModuleNames.Add("UEMorrowind");
    }
}
