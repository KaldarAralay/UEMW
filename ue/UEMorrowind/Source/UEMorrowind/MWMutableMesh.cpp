#include "MWMutableMesh.h"
#include "PrimitiveSceneProxy.h"
#include "DynamicMeshBuilder.h"
#include "LocalVertexFactory.h"
#include "StaticMeshResources.h"
#include "Materials/Material.h"
#include "Materials/MaterialRenderProxy.h"
#include "MaterialDomain.h"
#include "SceneManagement.h"
#include "RenderingThread.h"
#include "ProfilingDebugging/CpuProfilerTrace.h"

namespace {
void Tangents(FDynamicMeshVertex& D,const FProcMeshVertex& V) {
    D.TangentX=FVector3f(V.Tangent.TangentX);D.TangentZ=FVector3f(V.Normal);
    D.TangentZ.Vector.W=V.Tangent.bFlipTangentY?-127:127;
}
class FMWMutableProxy final : public FPrimitiveSceneProxy {
    FStaticMeshVertexBuffers Buffers;
    FDynamicMeshIndexBuffer32 Indices;
    FLocalVertexFactory Factory;
    FMaterialRenderProxy* Material;
    FMaterialRelevance Relevance;
    uint32 VertexCount=0;
    bool NativeBackground=false;
public:
    explicit FMWMutableProxy(UMWMutableMeshComponent* Component)
        :FPrimitiveSceneProxy(Component),Factory(GetScene().GetFeatureLevel(),"UEMWMutableMesh"),NativeBackground(Component->NativeBackground) {
        const auto* S=Component->GetProcMeshSection(0);
        auto* M=Component->GetMaterial(0);if(!M)M=UMaterial::GetDefaultMaterial(MD_Surface);
        Material=M->GetRenderProxy();Relevance=M->GetRelevance_Concurrent(GetScene().GetFeatureLevel());
        TArray<FDynamicMeshVertex> Vertices;Vertices.Reserve(S->ProcVertexBuffer.Num());
        for(const auto& V:S->ProcVertexBuffer) {
            FDynamicMeshVertex D(FVector3f(V.Position),FVector2f(V.UV0),V.Color);Tangents(D,V);
            D.TextureCoordinate[1]=FVector2f(V.UV1);D.TextureCoordinate[2]=FVector2f(V.UV2);D.TextureCoordinate[3]=FVector2f(V.UV3);Vertices.Add(D);
        }
        VertexCount=Vertices.Num();Indices.Indices=S->ProcIndexBuffer;
        Buffers.InitFromDynamicVertex(&Factory,Vertices,4);
        BeginInitResource(&Buffers.PositionVertexBuffer);BeginInitResource(&Buffers.StaticMeshVertexBuffer);BeginInitResource(&Buffers.ColorVertexBuffer);
        BeginInitResource(&Indices);BeginInitResource(&Factory);
    }
    virtual ~FMWMutableProxy(){Factory.ReleaseResource();Indices.ReleaseResource();Buffers.PositionVertexBuffer.ReleaseResource();Buffers.StaticMeshVertexBuffer.ReleaseResource();Buffers.ColorVertexBuffer.ReleaseResource();}
    virtual SIZE_T GetTypeHash() const override {static uint8 Identity;return reinterpret_cast<SIZE_T>(&Identity);}
    virtual uint32 GetMemoryFootprint() const override {return sizeof(*this)+VertexCount*sizeof(FDynamicMeshVertex)+Indices.Indices.GetAllocatedSize();}
    // Sky WPO places original near bounds at background depth. Querying that
    // near sphere causes false occlusion during movement; world depth testing
    // still occludes the rendered sky. Ordinary geometry keeps its queries.
    virtual bool CanBeOccluded() const override {return !NativeBackground && !Relevance.bDisableDepthTest;}
    virtual FPrimitiveViewRelevance GetViewRelevance(const FSceneView* View) const override {
        FPrimitiveViewRelevance Out;Out.bDrawRelevance=IsShown(View);Out.bDynamicRelevance=true;Out.bShadowRelevance=IsShadowCast(View);
        Out.bRenderInMainPass=ShouldRenderInMainPass();Out.bRenderCustomDepth=ShouldRenderCustomDepth();Out.bUsesLightingChannels=GetLightingChannelMask()!=GetDefaultLightingChannelMask();
        Relevance.SetPrimitiveViewRelevance(Out);Out.bVelocityRelevance=IsMovable() && Out.bOpaque && Out.bRenderInMainPass;return Out;
    }
    virtual void GetDynamicMeshElements(const TArray<const FSceneView*>& Views,const FSceneViewFamily&,uint32 Visible,FMeshElementCollector& Collector) const override {
        for(int32 I=0;I<Views.Num();++I)if(Visible&(1u<<I)) {
            auto& Mesh=Collector.AllocateMesh();Mesh.Type=PT_TriangleList;Mesh.VertexFactory=&Factory;Mesh.MaterialRenderProxy=Material;
            Mesh.DepthPriorityGroup=SDPG_World;Mesh.ReverseCulling=IsLocalToWorldDeterminantNegative();Mesh.CastShadow=IsShadowCast(Views[I]);
            auto& E=Mesh.Elements[0];E.IndexBuffer=&Indices;E.FirstIndex=0;E.NumPrimitives=Indices.Indices.Num()/3;E.MinVertexIndex=0;E.MaxVertexIndex=VertexCount-1;
            auto& Uniform=Collector.AllocateOneFrameResource<FDynamicPrimitiveUniformBuffer>();
            Uniform.Set(GetLocalToWorld(),GetLocalToWorld(),GetBounds(),GetLocalBounds(),GetLocalBounds(),true,false,false,GetCustomPrimitiveData());
            E.PrimitiveUniformBufferResource=&Uniform.UniformBuffer;Collector.AddMesh(I,Mesh);
        }
    }
    void Update(const TArray<FProcMeshVertex>& Vertices,uint8 Mask) {
        TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_MutableVertexUpload);
        check(IsInRenderingThread());if(Vertices.Num()!=int32(VertexCount))return;
        for(uint32 I=0;I<VertexCount;++I) {
            const auto& V=Vertices[I];if(Mask&1)Buffers.PositionVertexBuffer.VertexPosition(I)=FVector3f(V.Position);
            if(Mask&2){FDynamicMeshVertex D;Tangents(D,V);Buffers.StaticMeshVertexBuffer.SetVertexTangents(I,D.TangentX.ToFVector3f(),D.GetTangentY(),D.TangentZ.ToFVector3f());}
            if(Mask&4){auto& B=Buffers.StaticMeshVertexBuffer;B.SetVertexUV(I,0,FVector2f(V.UV0));B.SetVertexUV(I,1,FVector2f(V.UV1));B.SetVertexUV(I,2,FVector2f(V.UV2));B.SetVertexUV(I,3,FVector2f(V.UV3));}
            if(Mask&8)Buffers.ColorVertexBuffer.VertexColor(I)=V.Color;
        }
        auto Upload=[](const FBufferRHIRef& Buffer,const void* Data,uint32 Size){void* Dest=RHILockBuffer(Buffer,0,Size,RLM_WriteOnly);FMemory::Memcpy(Dest,Data,Size);RHIUnlockBuffer(Buffer);};
        if(Mask&1){auto& B=Buffers.PositionVertexBuffer;Upload(B.VertexBufferRHI,B.GetVertexData(),B.GetNumVertices()*B.GetStride());}
        if(Mask&2){auto& B=Buffers.StaticMeshVertexBuffer;Upload(B.TangentsVertexBuffer.VertexBufferRHI,B.GetTangentData(),B.GetTangentSize());}
        if(Mask&4){auto& B=Buffers.StaticMeshVertexBuffer;Upload(B.TexCoordVertexBuffer.VertexBufferRHI,B.GetTexCoordData(),B.GetTexCoordSize());}
        if(Mask&8){auto& B=Buffers.ColorVertexBuffer;Upload(B.VertexBufferRHI,B.GetVertexData(),B.GetNumVertices()*B.GetStride());}
    }
};
}
FPrimitiveSceneProxy* UMWMutableMeshComponent::CreateSceneProxy() {
    const auto* S=GetProcMeshSection(0);if(!S || !S->ProcVertexBuffer.Num() || !S->ProcIndexBuffer.Num() || S->ProcIndexBuffer.Num()%3)return nullptr;
    return new FMWMutableProxy(this);
}
FBoxSphereBounds UMWMutableMeshComponent::CalcBounds(const FTransform& LocalToWorld) const {
    const auto* S=const_cast<UMWMutableMeshComponent*>(this)->GetProcMeshSection(0);FBoxSphereBounds Out=S?FBoxSphereBounds(S->SectionLocalBox).TransformBy(LocalToWorld):FBoxSphereBounds(FVector::ZeroVector,FVector::ZeroVector,0);
    Out.BoxExtent*=BoundsScale;Out.SphereRadius*=BoundsScale;return Out;
}
bool UMWMutableMeshComponent::UpdateNativeSection(const TArray<FVector>& Points,const TArray<FVector>& Normals,const TArray<FVector2D>& UVs,const TArray<FVector2D>& Stage1,const TArray<FVector2D>& Stage2,const TArray<FLinearColor>& Colors) {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_MutableVertexPrepare);
    LastUploadMask=0;auto* S=GetProcMeshSection(0);const int32 N=Points.Num();
    if(!S || N!=S->ProcVertexBuffer.Num() || N<1 || N>65535 || Normals.Num()!=N || UVs.Num()!=N || Colors.Num()!=N || (Stage1.Num() && Stage1.Num()!=N) || (Stage2.Num() && Stage2.Num()!=N))return false;
    for(int32 I=0;I<N;++I)if(Points[I].ContainsNaN() || Normals[I].ContainsNaN() || UVs[I].ContainsNaN() || !FMath::IsFinite(Colors[I].R) || !FMath::IsFinite(Colors[I].G) || !FMath::IsFinite(Colors[I].B) || !FMath::IsFinite(Colors[I].A) || (Stage1.Num() && Stage1[I].ContainsNaN()) || (Stage2.Num() && Stage2[I].ContainsNaN()))return false;
    for(int32 I=0;I<N;++I) {
        auto& V=S->ProcVertexBuffer[I];const auto C=Colors[I].ToFColor(false);const auto U1=Stage1.Num()?Stage1[I]:FVector2D::ZeroVector,U2=Stage2.Num()?Stage2[I]:FVector2D::ZeroVector;
        if(V.Position!=Points[I]){V.Position=Points[I];LastUploadMask|=1;}
        if(V.Normal!=Normals[I]){V.Normal=Normals[I];LastUploadMask|=2;}
        if(V.UV0!=UVs[I] || V.UV1!=FVector2D::ZeroVector || V.UV2!=U1 || V.UV3!=U2){V.UV0=UVs[I];V.UV1=FVector2D::ZeroVector;V.UV2=U1;V.UV3=U2;LastUploadMask|=4;}
        if(V.Color!=C){V.Color=C;LastUploadMask|=8;}
    }
    if(!LastUploadMask)return true;
    if(SceneProxy && !IsRenderStateDirty()) {
        auto* Proxy=static_cast<FMWMutableProxy*>(SceneProxy);auto Vertices=S->ProcVertexBuffer;const uint8 Mask=LastUploadMask;
        ENQUEUE_RENDER_COMMAND(UEMWMutableVertices)([Proxy,Vertices=MoveTemp(Vertices),Mask](FRHICommandListImmediate&){Proxy->Update(Vertices,Mask);});++NativeUploadSubmissions;
    }
    S->SectionLocalBox=FBox(Points);UpdateBounds();MarkRenderTransformDirty();return true;
}
