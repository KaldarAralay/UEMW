#include "MWSkin.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/Material.h"
#include "MWLive.h"
#include "Engine/Texture2D.h"
#include "Engine/StaticMesh.h"
#include "Misc/FileHelper.h"
#include "HAL/FileManager.h"
#include "ProfilingDebugging/CpuProfilerTrace.h"
#include "TextureResource.h"
#include "Rendering/Texture2DResource.h"
#include "RHICommandList.h"

FBoxSphereBounds UMWNativeSkinComponent::CalcBounds(const FTransform& LocalToWorld) const {
    if(UseNativeBounds)return NativeBounds.TransformBy(GetComponentTransform().Inverse()*LocalToWorld);
    if(HaveNativeMatrix && GetStaticMesh()) {
        // CalcBounds(identity) is also used to obtain LOCAL culling bounds.
        // Retain the affine residual there, then honor the caller's placement.
        const FMatrix Residual=NativeMatrix*GetComponentTransform().ToInverseMatrixWithScale();
        return GetStaticMesh()->GetBounds().TransformBy(Residual*LocalToWorld.ToMatrixWithScale());
    }
    return Super::CalcBounds(LocalToWorld);
}
void UMWNativeSkinComponent::SetNativeMatrix(const FMatrix& Matrix,const FVector& Anchor,float Scale) {
    // FTransform drops affine shear. The original's animated foreground must
    // keep its exact matrix through both GPU submission and CPU culling.
    if(HaveNativeMatrix && NativeMatrix==Matrix && GetComponentLocation()==Anchor && GetComponentScale()==FVector(Scale))return;
    NativeMatrix=Matrix;HaveNativeMatrix=true;
    // Keep the primitive origin at the sampled display camera. Per-part
    // compressed translations would quantize tiny near-depth weapon parts at
    // large world coordinates; the shader carries their small relative offset.
    SetWorldTransform(FTransform(FQuat::Identity,Anchor,FVector(Scale)));
    UpdateBounds();MarkRenderTransformDirty();
}

void UMWNativeSkinComponent::SetNativeBounds(const FVector4f& B) {
    const float Radius=FMath::Max(1.f,B.W);
    if(NativeBounds.Origin==FVector(B.Y,B.X,B.Z) && NativeBounds.SphereRadius==Radius)return;
    NativeBounds=FBoxSphereBounds(FVector(B.Y,B.X,B.Z),FVector(Radius),Radius);
    UpdateBounds();MarkRenderTransformDirty();
}
bool MWLoadSkin(const FString& Path,FMWMeshData& Data) {
    const int64 Size=IFileManager::Get().FileSize(*Path);
    TArray<uint8> Raw;
    if(Size<16 || Size>8*1024*1024 || !FFileHelper::LoadFileToArray(Raw,*Path))return false;
    uint32 Count,Entries,Bones;FMemory::Memcpy(&Count,Raw.GetData()+4,4);FMemory::Memcpy(&Entries,Raw.GetData()+8,4);FMemory::Memcpy(&Bones,Raw.GetData()+12,4);
    if(FMemory::Memcmp(Raw.GetData(),"USK1",4) || Count!=Data.Vertices.Num() || !Entries || Entries>524288 || !Bones || Bones>257 || Raw.Num()!=16+(int64)Count*8+(int64)Entries*8)return false;
    Data.SkinUVs.SetNum(Count);Data.SkinWeights.SetNum(Entries);Data.SkinBones=Bones;
    for(uint32 i=0;i<Count;++i) {
        uint32 Range[2];FMemory::Memcpy(Range,Raw.GetData()+16+i*8,8);
        if(!Range[1] || Range[1]>512 || Range[0]>=Entries || Range[1]>Entries-Range[0])return false;
        Data.SkinUVs[i]=FVector2D(Range[0],Range[1]);
    }
    for(uint32 i=0;i<Entries;++i) {
        float Pair[2];FMemory::Memcpy(Pair,Raw.GetData()+16+Count*8+i*8,8);
        if(!FMath::IsFinite(Pair[0]) || Pair[0]<0 || Pair[0]>=Bones || Pair[0]!=FMath::FloorToFloat(Pair[0]) || !FMath::IsFinite(Pair[1]) || Pair[1]<0 || Pair[1]>1e8)return false;
        Data.SkinWeights[i]=FVector4f(Pair[0],Pair[1],0,0);
    }
    return true;
}
UTexture2D* MWFloatTexture(int32 Width,int32 Height,const TArray<FVector4f>& Values) {
    auto* Texture=UTexture2D::CreateTransient(Width,Height,PF_A32B32G32R32F);
    if(!Texture)return nullptr;
    Texture->SRGB=false;Texture->NeverStream=true;Texture->Filter=TF_Nearest;Texture->AddressX=TA_Clamp;Texture->AddressY=TA_Clamp;
    auto& Bulk=Texture->GetPlatformData()->Mips[0].BulkData;
    void* Memory=Bulk.Lock(LOCK_READ_WRITE);FMemory::Memzero(Memory,Width*Height*16);
    if(Values.Num())FMemory::Memcpy(Memory,Values.GetData(),FMath::Min(Values.Num(),Width*Height)*16);
    Bulk.Unlock();Texture->UpdateResource();return Texture;
}
UMaterialInstanceDynamic* MWMakeSkinMaterial(UObject* Owner,UMaterialInstanceDynamic* Template,UTexture2D* Palette) {
    if(!Template || !Template->GetMaterial() || !Palette)return nullptr;
    // UE rejects a dynamic instance as another instance's parent. Use the
    // cooked skin shader and copy its native texture/weight/light parameters.
    auto* Material=UMaterialInstanceDynamic::Create(Template->GetMaterial(),Owner);
    if(!Material)return nullptr;
    Material->CopyInterpParameters(Template);Material->SetTextureParameterValue(TEXT("BonePalette"),Palette);
    return Material;
}
bool MWUploadPalette(UTexture2D* Texture,const TArray<float>& Palette) {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_UploadBonePalette);
    FMWPaletteUploadBatch Batch;if(!Batch.Add(Texture,Palette))return false;Batch.Submit();return true;
}
bool FMWPaletteUploadBatch::Add(UTexture2D* Texture,const TArray<float>& Palette) {
    if(!Texture || Texture->GetSizeX()!=4 || !Palette.Num() || Palette.Num()%12 || Palette.Num()/12>Texture->GetSizeY())return false;
    if(GUsingNullRHI)return true; // Owned headless tests have no GPU resources.
    auto* Resource=Texture->GetResource()?Texture->GetResource()->GetTexture2DResource():nullptr;
    if(!Resource)return false;
    const int32 Rows=Palette.Num()/12;
    const int32 Offset=Pixels.AddZeroed(Rows*64);auto* Bytes=Pixels.GetData()+Offset;
    for(int32 Bone=0;Bone<Rows;++Bone)FMemory::Memcpy(Bytes+Bone*64,Palette.GetData()+Bone*12,48);
    Regions.Add({Resource,Rows,Offset});
    return true;
}
void FMWPaletteUploadBatch::Submit() {
    if(!Regions.Num())return;
    ENQUEUE_RENDER_COMMAND(UEMW_UpdateBonePalettes)([Regions=MoveTemp(Regions),Pixels=MoveTemp(Pixels)](FRHICommandListImmediate& RHICmdList)mutable {
        TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_UpdateBonePalettes);
        for(const auto& Region:Regions)RHIUpdateTexture2D(Region.Resource->TextureRHI->GetTexture2D(),0,FUpdateTextureRegion2D(0,0,0,0,4,Region.Rows),64,Pixels.GetData()+Region.Offset);
        // UpdateTexture2D may enqueue work for the separate RHI thread. Keep
        // the shared byte payload alive past every update, as UE's region API
        // does, rather than releasing it when this render command returns.
        RHICmdList.EnqueueLambda([Pixels=MoveTemp(Pixels)](FRHICommandList&){});
    });
}
bool MWUploadFloatPixels(UTexture2D* Texture,int32 Width,int32 Height,const TArray<FVector4f>& Values) {
    if(!Texture || Width!=Texture->GetSizeX() || Height!=Texture->GetSizeY() || Values.Num()!=Width*Height)return false;
    auto* Bytes=new uint8[Values.Num()*16];FMemory::Memcpy(Bytes,Values.GetData(),Values.Num()*16);
    auto* Region=new FUpdateTextureRegion2D(0,0,0,0,Width,Height);
    Texture->UpdateTextureRegions(0,1,Region,Width*16,16,Bytes,[](uint8* Data,const FUpdateTextureRegion2D* Regions){delete[] Data;delete Regions;});
    return true;
}
