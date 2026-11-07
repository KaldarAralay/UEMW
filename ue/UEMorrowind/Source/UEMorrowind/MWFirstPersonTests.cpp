#include "MWLive.h"
#include "MWCamera.h"
#include "MWMesh.h"
#include "MWSkin.h"
#include "Camera/CameraComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Kismet/KismetRenderingLibrary.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/AutomationTest.h"
#include "Misc/ScopeExit.h"
#include "RenderingThread.h"
#include "RHI.h"
#include "TextureResource.h"
#include "PrimitiveSceneProxy.h"
#include "MWMutableMesh.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWFirstPersonPresentationTest,"UEMW.Renderer.FirstPersonPresentation",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWFirstPersonPresentationTest::RunTest(const FString&) {
    const FString MutablePacket=TEXT(R"JSON({"protocol":"uemw.camera","version":2,"pid":42,"session":"11111111-1111-1111-1111-111111111111","scene_epoch":"22222222-2222-2222-2222-222222222222","sequence":1,"source_sequence":1,"sample_unix_ns":100000000000,"camera":{"position":[0,0,0],"forward":[0,1,0],"up":[0,0,1],"fov":75},"view":{"protocol":"uemw.view","version":2,"catalog":"owned","sample_unix_ns":100000000100,"camera":{"position":[0,0,0],"forward":[0,1,0],"up":[0,0,1]},"states":[{"id":"m","asset":"m","visible":true,"transform":[1,0,0,0,1,0,0,0,1,0,0,0,1],"points":[0,0,0,1,0,0,0,1,0],"uvs":[0,0,1,0,0,1]}]}})JSON");
    FMWCameraSample Decoded;
    TestTrue(TEXT("Versioned native near morph/UV payload decodes"),MWDecodeCamera(MutablePacket,Decoded));
    TestEqual(TEXT("Resolved near vertices are retained exactly"),Decoded.ViewStates.Num()?Decoded.ViewStates[0].Pose.Points.Num():0,9);
    TestFalse(TEXT("Near v1 cannot silently accept a v2 morph extension"),MWDecodeCamera(MutablePacket.Replace(TEXT("\"uemw.view\",\"version\":2"),TEXT("\"uemw.view\",\"version\":1")),Decoded));
    TestFalse(TEXT("Partial resolved near UVs reject the complete sample"),MWDecodeCamera(MutablePacket.Replace(TEXT("\"uvs\":[0,0,1,0,0,1]"),TEXT("\"uvs\":[0,0]")),Decoded));
    UWorld* World=nullptr;for(const auto& C:GEngine->GetWorldContexts())if(C.WorldType==EWorldType::Game && C.World()){World=C.World();break;}
    if(!World){AddError(TEXT("Owned foreground fixture requires a runtime world"));return false;}
    auto* V=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!V)return false;ON_SCOPE_EXIT {V->ResetScene();V->Destroy();};
    V->CreateGeometryMaterial();V->Catalog=V->ResourceCatalog=TEXT("owned-view");
    FMWMeshData Blade;Blade.FirstPerson=true;Blade.Vertices={FVector(-3,0,-5),FVector(3,0,-5),FVector(3,0,45),FVector(-3,0,45)};Blade.Normals.Init(FVector(0,-1,0),4);Blade.UVs={FVector2D(0,0),FVector2D(1,0),FVector2D(1,1),FVector2D(0,1)};Blade.Colors.Init(FLinearColor(1,.2,.05,1),4);Blade.Triangles={0,1,2,0,2,3};
    auto* Material=UMaterialInstanceDynamic::Create(V->GeometryBaseMaterial,V);
    Material->SetScalarParameterValue(TEXT("NativeLit"),0);Material->SetScalarParameterValue(TEXT("NativeFog"),0);Material->SetScalarParameterValue(TEXT("NativeModernLighting"),0);Material->SetScalarParameterValue(TEXT("NativeEffectQuality"),0);Material->SetTextureParameterValue(TEXT("NativeEnvironment"),MWFloatTexture(8,33,{}));
    for(const FString Asset:{FString(TEXT("blade")),FString(TEXT("other"))}) {
        auto D=Blade;if(Asset==TEXT("other")){D.Vertices[2].Z=58;D.Vertices[3].Z=58;}
        V->MeshData.Add(Asset,D);V->GeometryMaterials.Add(Asset,Material);V->ViewCachedAssets.Add(Asset);V->SharedMeshes.Add(Asset,MWBuildMesh(V,D,Material));
    }
    auto* MID=UMaterialInstanceDynamic::Create(Material->GetMaterial(),V);MID->CopyInterpParameters(Material);
    auto* Native=NewObject<UMWNativeSkinComponent>(V);Native->UseNativeBounds=false;Native->SetMobility(EComponentMobility::Movable);Native->SetStaticMesh(V->SharedMeshes[TEXT("blade")]);Native->SetMaterial(0,MID);Native->SetCollisionEnabled(ECollisionEnabled::NoCollision);Native->SetCastShadow(false);Native->RegisterComponent();
    V->SkinnedComponents.Add(TEXT("held"),Native);V->SkinMaterials.Add(TEXT("held"),MID);V->SetInstanceAsset(TEXT("held"),TEXT("blade"));V->ResourceBindings.Add(TEXT("held"),TEXT("blade"));
    auto HandData=Blade;HandData.SkinBones=1;HandData.SkinUVs.Init(FVector2D(0,1),4);HandData.SkinWeights={FVector4f(0,1,0,0)};
    auto* HandTemplate=UMaterialInstanceDynamic::Create(V->SkinBaseMaterials[TEXT("opaque")],V);HandTemplate->CopyInterpParameters(Material);HandTemplate->SetTextureParameterValue(TEXT("SkinWeights"),MWFloatTexture(1024,1,HandData.SkinWeights));
    auto* HandPalette=MWFloatTexture(4,1,{});auto* HandMID=MWMakeSkinMaterial(V,HandTemplate,HandPalette);auto* HandMesh=MWBuildMesh(V,HandData,HandTemplate);
    auto* Hand=NewObject<UMWNativeSkinComponent>(V);Hand->SetMobility(EComponentMobility::Movable);Hand->SetStaticMesh(HandMesh);Hand->SetMaterial(0,HandMID);Hand->SetCollisionEnabled(ECollisionEnabled::NoCollision);Hand->SetCastShadow(false);Hand->SetNativeBounds(FVector4f(0,0,0,1));Hand->RegisterComponent();
    V->MeshData.Add(TEXT("hand"),HandData);V->GeometryMaterials.Add(TEXT("hand"),HandTemplate);V->SharedMeshes.Add(TEXT("hand"),HandMesh);V->ViewCachedAssets.Add(TEXT("hand"));V->PaletteTextures.Add(TEXT("hand"),HandPalette);V->SkinnedComponents.Add(TEXT("hand"),Hand);V->SkinMaterials.Add(TEXT("hand"),HandMID);V->SetInstanceAsset(TEXT("hand"),TEXT("hand"));V->ResourceBindings.Add(TEXT("hand"),TEXT("hand"));
    auto MorphData=Blade;MorphData.NativeVertices=true;MorphData.NativeUVs=true;MorphData.Triangles={0,2,1,0,3,2};V->MeshData.Add(TEXT("morph"),MorphData);V->GeometryMaterials.Add(TEXT("morph"),Material);V->ViewCachedAssets.Add(TEXT("morph"));V->ResourceBindings.Add(TEXT("morph"),TEXT("morph"));TestTrue(TEXT("Owned native-morph resource prepares"),V->PrepareMutableResource(TEXT("morph"),TEXT("morph")));auto* Morph=V->GeometryComponents.FindRef(TEXT("morph"));
    auto* Reference=NewObject<UStaticMeshComponent>(V);Reference->SetMobility(EComponentMobility::Movable);Reference->SetCollisionEnabled(ECollisionEnabled::NoCollision);Reference->SetCastShadow(false);Reference->SetMaterial(0,Material);
    UTextureRenderTarget2D* Target=nullptr;USceneCaptureComponent2D* Capture=nullptr;
    if(!GUsingNullRHI) {
        Target=UKismetRenderingLibrary::CreateRenderTarget2D(World,128,128,RTF_RGBA16f,FLinearColor::Black,false);
        Capture=NewObject<USceneCaptureComponent2D>(V);Capture->TextureTarget=Target;Capture->FOVAngle=75;Capture->CaptureSource=SCS_SceneColorHDRNoAlpha;Capture->bCaptureEveryFrame=false;Capture->bCaptureOnMovement=false;Capture->PrimitiveRenderMode=ESceneCapturePrimitiveRenderMode::PRM_UseShowOnlyList;Capture->ShowFlags.SetPostProcessing(false);Capture->ShowFlags.SetAntiAliasing(false);Capture->RegisterComponent();
    }
    ON_SCOPE_EXIT {Reference->DestroyComponent();if(Capture){Capture->DestroyComponent();UKismetRenderingLibrary::ReleaseRenderTarget2D(Target);}};
    auto Image=[&](UPrimitiveComponent* C){World->SendAllEndOfFrameUpdates();Capture->ShowOnlyComponents={C};Capture->HiddenComponents.Empty();if((C==Native && !V->InstanceSubmitted(TEXT("held"))) || (C==Hand && !V->InstanceSubmitted(TEXT("hand"))) || (C==Morph && !V->InstanceSubmitted(TEXT("morph"))))Capture->HiddenComponents.Add(C);Capture->CaptureScene();FlushRenderingCommands();TArray<FLinearColor> Pixels;Target->GameThread_GetRenderTargetResource()->ReadLinearColorPixels(Pixels);return Pixels;};
    // A source camera far from the origin, a separately sampled display camera,
    // native affine/mirrored animation, hide/show and same-address replacement.
    // Reference triangles are independently baked from all 13 native values;
    // checking only the component origin cannot catch a missing/distorted blade.
    const FVector SourceNative(-9544,-72436,183),SourceUE(SourceNative.Y,SourceNative.X,SourceNative.Z);
    for(int32 Phase=0;Phase<9;++Phase) {
        double M[13]={1,0,0,0,1,0,0,0,1,SourceNative.X+5,SourceNative.Y+50,SourceNative.Z-20,1};
        if(Phase==1)M[1]=.0002; // crosses the former decomposition cutoff
        if(Phase==2 || Phase==3 || Phase==7)M[2]=.35;
        if(Phase==3)M[0]=-1;
        if(Phase==4){M[0]=.8;M[1]=-.4;M[3]=.6;M[4]=1.2;M[8]=.9;}
        const bool Shown=Phase!=5 && Phase!=8;const FString Asset=Phase>=7?TEXT("other"):TEXT("blade");
        const FTransform Display(FRotator(Phase*2,Phase*17,0),SourceUE+FVector(Phase*37,-Phase*18,Phase*5));
        V->Camera->SetWorldTransform(Display);
        FMWCameraSample Sample;Sample.ViewCatalog=V->Catalog;Sample.ViewStamp=100+Phase;Sample.ViewCamera=FTransform(FQuat::Identity,SourceUE);
        FMWViewState Part;Part.Id=TEXT("held");Part.Asset=Asset;Part.Pose.Visible=Shown;for(int32 I=0;I<13;++I)Part.Pose.Transform[I]=(float)M[I];Sample.ViewStates.Add(Part);
        auto HandPose=Part;HandPose.Id=HandPose.Asset=TEXT("hand");for(int32 R=0;R<3;++R){for(int32 C=0;C<3;++C)HandPose.Pose.Palette.Add((float)(M[R*3+C]*M[12]));HandPose.Pose.Palette.Add((float)M[9+R]);}HandPose.Pose.Bound=FVector4f(M[9],M[10],M[11],90);Sample.ViewStates.Add(HandPose);
        auto MorphPose=Part;MorphPose.Id=MorphPose.Asset=TEXT("morph");auto CurrentMorph=MorphData;
        for(int32 I=0;I<CurrentMorph.Vertices.Num();++I){auto& P=CurrentMorph.Vertices[I];if(I>=2){P.X+=Phase;P.Z+=Phase*2;}for(double N:{P.X,P.Y,P.Z})MorphPose.Pose.Points.Add((float)N);MorphPose.Pose.UVs.Add((float)CurrentMorph.UVs[I].X);MorphPose.Pose.UVs.Add((float)CurrentMorph.UVs[I].Y);}Sample.ViewStates.Add(MorphPose);
        V->ApplyFirstPersonLane(Sample,Sample.ViewStamp+.01);V->UpdateViewCorrection();
        TestEqual(FString::Printf(TEXT("Native foreground affine phase %d is submitted without a fallback gap"),Phase),V->InstanceSubmitted(TEXT("held")),Shown);
        TestTrue(TEXT("Animation and redraw retain the existing foreground component"),V->SkinnedComponents.FindRef(TEXT("held"))==Native);
        TestEqual(TEXT("Exact foreground animation queues no alternate CPU mesh"),V->ResourceJobs.Num(),0);
        TestTrue(TEXT("Foreground adds no Unreal gameplay collision or simulation"),Native->GetCollisionEnabled()==ECollisionEnabled::NoCollision && !Native->IsSimulatingPhysics());
        TestEqual(TEXT("Skin visibility follows the same native foreground pass"),V->InstanceSubmitted(TEXT("hand")),Shown);
        TestTrue(TEXT("Native hand palette retains its static geometry and camera origin"),Hand->GetStaticMesh()==HandMesh && Hand->GetComponentLocation().Equals(Display.GetLocation(),.00001));
        TestEqual(TEXT("Resolved native morph visibility follows its near sample"),V->InstanceSubmitted(TEXT("morph")),Shown);
        TestTrue(TEXT("Native morph does not switch or recreate its drawable"),V->GeometryComponents.FindRef(TEXT("morph"))==Morph);
        if(!Capture)continue;
        auto RefData=V->MeshData[Asset];RefData.FirstPerson=false;
        for(auto& P:RefData.Vertices){const FVector Q=P;P=FVector((M[0]*Q.X+M[1]*Q.Y+M[2]*Q.Z)*M[12]+M[9]-SourceNative.X,(M[3]*Q.X+M[4]*Q.Y+M[5]*Q.Z)*M[12]+M[10]-SourceNative.Y,(M[6]*Q.X+M[7]*Q.Y+M[8]*Q.Z)*M[12]+M[11]-SourceNative.Z);}
        if(Phase==3)for(int32 I=0;I<RefData.Triangles.Num();I+=3)Swap(RefData.Triangles[I+1],RefData.Triangles[I+2]);
        FVector RefNormal=FVector::CrossProduct(RefData.Vertices[1]-RefData.Vertices[0],RefData.Vertices[2]-RefData.Vertices[0]).GetSafeNormal();if(Phase==3)RefNormal=-RefNormal;RefData.Normals.Init(RefNormal,RefData.Vertices.Num());
        // Use the ordinary, non-view shader on the independent baked reference.
        auto* RefMID=UMaterialInstanceDynamic::Create(Material->GetMaterial(),V);RefMID->CopyInterpParameters(Material);RefMID->SetScalarParameterValue(TEXT("NativeViewActive"),0);
        Reference->SetStaticMesh(MWBuildMesh(V,RefData,RefMID));Reference->SetMaterial(0,RefMID);Reference->SetWorldTransform(FTransform(Display.GetRotation(),Display.GetLocation(),FVector(MWFirstPersonDepthScale)));if(!Reference->IsRegistered())Reference->RegisterComponent();Reference->SetVisibility(Shown);
        if(Shown)for(int32 I=0;I<RefData.Vertices.Num();++I) {
            const auto P=V->MeshData[Asset].Vertices[I],R=RefData.Vertices[I];
            const FVector Actual=Native->GetNativeMatrix().TransformPosition(FVector(P.Y,P.X,P.Z));
            const FVector Expected=Reference->GetComponentTransform().TransformPosition(FVector(R.Y,R.X,R.Z));
            TestTrue(FString::Printf(TEXT("Foreground full matrix preserves reference vertex phase=%d vertex=%d error=%.9f"),Phase,I,(Actual-Expected).Size()),Actual.Equals(Expected,.0001));
        }
        Capture->SetWorldTransform(Display);
        const auto A=Image(Native),B=Image(Reference);TestTrue(TEXT("Render proxy receives the primitive matrix used by the residual shader"),Native->SceneProxy && Native->SceneProxy->GetLocalToWorld().Equals(Native->GetRenderMatrix(),.0001));TestEqual(TEXT("Foreground comparison reads real GPU pixels"),A.Num(),128*128);int32 Different=0,Visible=0,RefVisible=0;double Error=0;
        for(int32 I=0;I<FMath::Min(A.Num(),B.Num());++I){const auto& X=A[I];const auto& Y=B[I];const float D=FMath::Max3(FMath::Abs(X.R-Y.R),FMath::Abs(X.G-Y.G),FMath::Abs(X.B-Y.B));Different+=D>.03f;Error+=FMath::Abs(X.R-Y.R)+FMath::Abs(X.G-Y.G)+FMath::Abs(X.B-Y.B);Visible+=FMath::Max3(X.R,X.G,X.B)>.01f;RefVisible+=FMath::Max3(Y.R,Y.G,Y.B)>.01f;}
        AddInfo(FString::Printf(TEXT("Foreground GPU phase=%d visible=%d reference=%d mismatch=%d absoluteRGB=%.6f"),Phase,Visible,RefVisible,Different,Error));
        TestTrue(TEXT("Full weapon silhouette matches independently transformed native vertices"),Different<8 && Error<.001*FMath::Max(1,A.Num()));
        TestTrue(TEXT("Weapon pixels disappear only when original visibility requests it"),Shown?(Visible>100 && RefVisible>100):(Visible==0 && RefVisible==0));
        if(Phase>=7) {
            // The same hand geometry stays equipped when the rigid blade is
            // replaced; use its independent CPU reference, not the longer blade.
            auto HandRef=Blade;HandRef.FirstPerson=false;
            for(auto& P:HandRef.Vertices){const FVector Q=P;P=FVector((M[0]*Q.X+M[1]*Q.Y+M[2]*Q.Z)*M[12]+M[9]-SourceNative.X,(M[3]*Q.X+M[4]*Q.Y+M[5]*Q.Z)*M[12]+M[10]-SourceNative.Y,(M[6]*Q.X+M[7]*Q.Y+M[8]*Q.Z)*M[12]+M[11]-SourceNative.Z);}
            HandRef.Normals.Init(RefNormal,4);Reference->SetStaticMesh(MWBuildMesh(V,HandRef,RefMID));
        }
        const auto H=Image(Hand),HR=Image(Reference);int32 HandDifferent=0,HandVisible=0;double HandError=0;
        for(int32 I=0;I<FMath::Min(H.Num(),HR.Num());++I){const auto& X=H[I];const auto& Y=HR[I];HandDifferent+=FMath::Max3(FMath::Abs(X.R-Y.R),FMath::Abs(X.G-Y.G),FMath::Abs(X.B-Y.B))>.03f;HandError+=FMath::Abs(X.R-Y.R)+FMath::Abs(X.G-Y.G)+FMath::Abs(X.B-Y.B);HandVisible+=FMath::Max3(X.R,X.G,X.B)>.01f;}
        AddInfo(FString::Printf(TEXT("Foreground hand GPU phase=%d visible=%d mismatch=%d absoluteRGB=%.6f"),Phase,HandVisible,HandDifferent,HandError));
        TestTrue(TEXT("Camera-relative native hand skin matches the CPU reference in real pixels"),HandDifferent<8 && HandError<.001*FMath::Max(1,H.Num()));
        TestTrue(TEXT("Skin pixels follow original hide and restore"),Shown?HandVisible>100:HandVisible==0);
        auto MorphRef=CurrentMorph;MorphRef.NativeVertices=MorphRef.NativeUVs=MorphRef.FirstPerson=false;
        for(auto& P:MorphRef.Vertices){const FVector T=P;P=FVector((M[0]*T.X+M[1]*T.Y+M[2]*T.Z)*M[12]+M[9]-SourceNative.X,(M[3]*T.X+M[4]*T.Y+M[5]*T.Z)*M[12]+M[10]-SourceNative.Y,(M[6]*T.X+M[7]*T.Y+M[8]*T.Z)*M[12]+M[11]-SourceNative.Z);}
        MorphRef.Normals.Init(FVector::ZeroVector,4);for(int32 I=0;I<MorphRef.Triangles.Num();I+=3){const int32 A0=MorphRef.Triangles[I],B0=MorphRef.Triangles[I+1],C0=MorphRef.Triangles[I+2];const FVector N=FVector::CrossProduct(FVector(MorphRef.Vertices[B0].Y,MorphRef.Vertices[B0].X,MorphRef.Vertices[B0].Z)-FVector(MorphRef.Vertices[A0].Y,MorphRef.Vertices[A0].X,MorphRef.Vertices[A0].Z),FVector(MorphRef.Vertices[C0].Y,MorphRef.Vertices[C0].X,MorphRef.Vertices[C0].Z)-FVector(MorphRef.Vertices[A0].Y,MorphRef.Vertices[A0].X,MorphRef.Vertices[A0].Z));for(int32 J:{A0,B0,C0})MorphRef.Normals[J]+=FVector(N.Y,N.X,N.Z);}for(auto& N:MorphRef.Normals)N.Normalize();
        Reference->SetStaticMesh(MWBuildMesh(V,MorphRef,RefMID));const auto MP=Image(Morph),MR=Image(Reference);int32 MorphDifferent=0,MorphVisible=0;double MorphError=0;
        for(int32 I=0;I<FMath::Min(MP.Num(),MR.Num());++I){const auto& X=MP[I];const auto& Y=MR[I];MorphDifferent+=FMath::Max3(FMath::Abs(X.R-Y.R),FMath::Abs(X.G-Y.G),FMath::Abs(X.B-Y.B))>.03f;MorphError+=FMath::Abs(X.R-Y.R)+FMath::Abs(X.G-Y.G)+FMath::Abs(X.B-Y.B);MorphVisible+=FMath::Max3(X.R,X.G,X.B)>.01f;}
        AddInfo(FString::Printf(TEXT("Foreground morph GPU phase=%d visible=%d mismatch=%d absoluteRGB=%.6f"),Phase,MorphVisible,MorphDifferent,MorphError));TestTrue(TEXT("Resolved native morph matches CPU reference in real GPU pixels"),MorphDifferent<8 && MorphError<.001*FMath::Max(1,MP.Num()));TestTrue(TEXT("Morph pixels follow original hide/restore"),Shown?MorphVisible>100:MorphVisible==0);
    }
    return true;
}
