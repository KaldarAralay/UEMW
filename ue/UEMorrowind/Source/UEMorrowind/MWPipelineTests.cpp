#include "MWPipeline.h"
#include "MWMutableMesh.h"
#include "MWLines.h"
#include "LocalVertexFactory.h"
#include "Materials/MaterialInterface.h"
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWPipelineWarmupTest,"UEMW.Renderer.PipelineWarmup",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWPipelineWarmupTest::RunTest(const FString&) {
    auto* Material=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/UEMW/Materials/MW_Opaque.MW_Opaque"));
    if(!TestNotNull(TEXT("Actual cooked shader family exists"),Material))return false;
    auto* Shape=NewObject<UMWMutableMeshComponent>();auto* Line=NewObject<UMWNativeLineComponent>();
    FPSOPrecacheParams Base;Base.SetMobility(EComponentMobility::Movable);Base.bStaticLighting=false;Base.bRenderCustomDepth=true;
    UPrimitiveComponent::FComponentPSOPrecacheParamsList Params;
    Shape->SetMaterial(0,Material);Shape->SetWorldScale3D(FVector(-2,3,4));
    Shape->CollectPSOPrecacheData(Base,Params);
    if(!TestEqual(TEXT("Resolved mutable geometry supplies the missing procedural collector"),Params.Num(),1))return false;
    TestEqual(TEXT("Collector uses the actual shader resource"),Params[0].MaterialInterface,Material);
    TestTrue(TEXT("Mutable proxy's real local vertex factory is selected"),Params[0].VertexFactoryDataList[0].VertexFactoryType==&FLocalVertexFactory::StaticType);
    TestEqual(TEXT("Triangles keep triangle topology"),(int32)Params[0].PSOPrecacheParams.PrimitiveType,(int32)PT_TriangleList);
    TestTrue(TEXT("Mirrored mutable geometry collects reverse culling"),Params[0].PSOPrecacheParams.bReverseCulling!=0);
    TestTrue(TEXT("Native water custom-depth selection is retained"),Params[0].PSOPrecacheParams.bRenderCustomDepth!=0);
    TestFalse(TEXT("Movable geometry does not acquire baked lighting"),Params[0].PSOPrecacheParams.bStaticLighting!=0);
    TestTrue(TEXT("Collection does not hide the native primitive"),Shape->GetVisibleFlag());
    Params.Empty();Line->SetMaterial(0,Material);Line->CollectPSOPrecacheData(Base,Params);
    if(!TestEqual(TEXT("Native lines supply a collector too"),Params.Num(),1))return false;
    TestEqual(TEXT("Lines are not warmed as carrier triangles"),(int32)Params[0].PSOPrecacheParams.PrimitiveType,(int32)PT_LineList);
    TestTrue(TEXT("Line proxy disables culling"),Params[0].PSOPrecacheParams.bDisableBackFaceCulling!=0);
    TestFalse(TEXT("Lines do not acquire shadow simulation"),Params[0].PSOPrecacheParams.bCastShadow!=0);
    FMWPipelineWarmup Warmup;Warmup.AddMaterial(nullptr,true,false);TestTrue(TEXT("No material starts no work"),Warmup.Ready());
    Warmup.AddMaterial(Material,true,false);Warmup.Advance(0);
    TestEqual(TEXT("Zero submission allowance cannot consume the queue"),Warmup.Submitted,0);
    if(PipelineStateCache::IsPSOPrecachingEnabled()) {
        Warmup.Advance(1,0);TestEqual(TEXT("One bounded call submits only one culling variant"),Warmup.Submitted,1);
        TestTrue(TEXT("Selected family is submitted without unused culling variants"),Warmup.Queued()==0);
        Warmup.AddMaterial(Material,false,false);Warmup.AddMaterial(Material,true,false);Warmup.Advance(1,0);
        TestEqual(TEXT("Repeated family selection reuses the same warmup request"),Warmup.Submitted,1);
        TestEqual(TEXT("Submission remains accounted without waiting"),Warmup.Completed+Warmup.Pending(),1);
    }
    return true;
}
