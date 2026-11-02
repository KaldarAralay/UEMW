using UnrealBuildTool;
public class UEMorrowind : ModuleRules {
    public UEMorrowind(ReadOnlyTargetRules Target) : base(Target) {
        PCHUsage=PCHUsageMode.UseExplicitOrSharedPCHs;
        // Each source owns its includes and file-local helpers. Adding a file
        // must not change which Windows macros/helpers leak across unity lumps.
        bUseUnity=false;
        PublicDependencyModuleNames.AddRange(new[]{"Core","CoreUObject","Engine","InputCore","Json","ProceduralMeshComponent","SlateCore","ApplicationCore"});
        PrivateDependencyModuleNames.AddRange(new[]{"RenderCore","RHI","MeshDescription","StaticMeshDescription","ImageCore"});
        if(Target.bBuildEditor)PrivateDependencyModuleNames.Add("AssetRegistry");
    }
}
