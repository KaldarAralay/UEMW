#include "MWLines.h"
#include "PrimitiveSceneProxy.h"
#include "DynamicMeshBuilder.h"
#include "LocalVertexFactory.h"
#include "StaticMeshResources.h"
#include "Materials/Material.h"
#include "Materials/MaterialRenderProxy.h"
#include "MaterialDomain.h"
#include "SceneManagement.h"

namespace {
class FMWLineProxy final : public FPrimitiveSceneProxy {
    FStaticMeshVertexBuffers Buffers;
    FDynamicMeshIndexBuffer32 Indices;
    FLocalVertexFactory Factory;
    FMaterialRenderProxy* Material;
    FMaterialRelevance Relevance;
    uint32 VertexCount=0;
public:
    explicit FMWLineProxy(UMWNativeLineComponent* Component)
        :FPrimitiveSceneProxy(Component),Factory(GetScene().GetFeatureLevel(),"UEMWNativeLines") {
        const auto* Section=Component->GetProcMeshSection(0);
        auto* M=Component->GetMaterial(0);if(!M)M=UMaterial::GetDefaultMaterial(MD_Surface);
        Material=M->GetRenderProxy();Relevance=M->GetRelevance_Concurrent(GetScene().GetFeatureLevel());
        TArray<FDynamicMeshVertex> Vertices;Vertices.Reserve(Section->ProcVertexBuffer.Num());
        for(const auto& V:Section->ProcVertexBuffer) {
            FDynamicMeshVertex D(FVector3f(V.Position),FVector2f(V.UV0),V.Color);
            D.TextureCoordinate[1]=FVector2f(V.UV1);D.TextureCoordinate[2]=FVector2f(V.UV2);D.TextureCoordinate[3]=FVector2f(V.UV3);
            Vertices.Add(D);
        }
        VertexCount=Vertices.Num();
        for(int32 I=0;I<Section->ProcIndexBuffer.Num();I+=3){Indices.Indices.Add(Section->ProcIndexBuffer[I]);Indices.Indices.Add(Section->ProcIndexBuffer[I+1]);}
        Buffers.InitFromDynamicVertex(&Factory,Vertices,4);
        BeginInitResource(&Buffers.PositionVertexBuffer);BeginInitResource(&Buffers.StaticMeshVertexBuffer);BeginInitResource(&Buffers.ColorVertexBuffer);
        BeginInitResource(&Indices);BeginInitResource(&Factory);
    }
    virtual ~FMWLineProxy() {
        Factory.ReleaseResource();Indices.ReleaseResource();Buffers.PositionVertexBuffer.ReleaseResource();Buffers.StaticMeshVertexBuffer.ReleaseResource();Buffers.ColorVertexBuffer.ReleaseResource();
    }
    virtual SIZE_T GetTypeHash() const override {static uint8 Identity;return reinterpret_cast<SIZE_T>(&Identity);}
    virtual uint32 GetMemoryFootprint() const override {return sizeof(*this)+VertexCount*sizeof(FDynamicMeshVertex)+Indices.Indices.GetAllocatedSize();}
    virtual FPrimitiveViewRelevance GetViewRelevance(const FSceneView* View) const override {
        FPrimitiveViewRelevance Out;Out.bDrawRelevance=IsShown(View);Out.bDynamicRelevance=true;Out.bShadowRelevance=false;
        Out.bRenderInMainPass=ShouldRenderInMainPass();Out.bRenderCustomDepth=ShouldRenderCustomDepth();Relevance.SetPrimitiveViewRelevance(Out);return Out;
    }
    virtual void GetDynamicMeshElements(const TArray<const FSceneView*>& Views,const FSceneViewFamily&,uint32 Visible,FMeshElementCollector& Collector) const override {
        for(int32 I=0;I<Views.Num();++I)if(Visible&(1u<<I)) {
            auto& Mesh=Collector.AllocateMesh();Mesh.Type=PT_LineList;Mesh.VertexFactory=&Factory;Mesh.MaterialRenderProxy=Material;
            Mesh.DepthPriorityGroup=SDPG_World;Mesh.bDisableBackfaceCulling=true;Mesh.CastShadow=false;
            auto& E=Mesh.Elements[0];E.IndexBuffer=&Indices;E.FirstIndex=0;E.NumPrimitives=Indices.Indices.Num()/2;E.MinVertexIndex=0;E.MaxVertexIndex=VertexCount-1;
            auto& Uniform=Collector.AllocateOneFrameResource<FDynamicPrimitiveUniformBuffer>();
            Uniform.Set(GetLocalToWorld(),GetLocalToWorld(),GetBounds(),GetLocalBounds(),GetLocalBounds(),false,false,false,GetCustomPrimitiveData());
            E.PrimitiveUniformBufferResource=&Uniform.UniformBuffer;Collector.AddMesh(I,Mesh);
        }
    }
};
}
bool UMWNativeLineComponent::SetNativeSection(const TArray<FVector>& Points,const TArray<int32>& Carrier,const TArray<FVector2D>& UVs,const TArray<FVector2D>& UV1,const TArray<FVector2D>& UV2,const TArray<FLinearColor>& Colors) {
    if(Points.Num()<1 || Points.Num()>65535 || Carrier.Num()==0 || Carrier.Num()%3 || UVs.Num()!=Points.Num() || Colors.Num()!=Points.Num() || (UV1.Num() && UV1.Num()!=Points.Num()) || (UV2.Num() && UV2.Num()!=Points.Num()))return false;
    for(int32 I=0;I<Carrier.Num();I+=3)if(Carrier[I]<0 || Carrier[I]>=Points.Num() || Carrier[I+1]<0 || Carrier[I+1]>=Points.Num() || Carrier[I+1]!=Carrier[I+2])return false;
    FProcMeshSection S;S.ProcVertexBuffer.SetNum(Points.Num());
    for(int32 I=0;I<Points.Num();++I) {
        if(Points[I].ContainsNaN())return false;
        auto& V=S.ProcVertexBuffer[I];V.Position=Points[I];V.Normal=FVector::UpVector;V.UV0=UVs[I];V.Color=Colors[I].ToFColor(false);
        V.UV1=FVector2D::ZeroVector;V.UV2=UV1.Num()?UV1[I]:FVector2D::ZeroVector;V.UV3=UV2.Num()?UV2[I]:FVector2D::ZeroVector;
        S.SectionLocalBox+=Points[I];
    }
    for(int32 I:Carrier)S.ProcIndexBuffer.Add(I);
    S.SectionLocalBox=S.SectionLocalBox.ExpandBy(.5);S.bEnableCollision=false;
    // The triangle builder intentionally discards carrier triples. Store a
    // validated line section directly; only our PT_LineList proxy consumes it.
    SetProcMeshSection(0,S);return true;
}
FPrimitiveSceneProxy* UMWNativeLineComponent::CreateSceneProxy() {
    const auto* S=GetProcMeshSection(0);
    if(!S || S->ProcVertexBuffer.Num()==0 || S->ProcIndexBuffer.Num()==0 || S->ProcIndexBuffer.Num()%3)return nullptr;
    for(int32 I=0;I<S->ProcIndexBuffer.Num();I+=3)if(S->ProcIndexBuffer[I]>=uint32(S->ProcVertexBuffer.Num()) || S->ProcIndexBuffer[I+1]>=uint32(S->ProcVertexBuffer.Num()) || S->ProcIndexBuffer[I+1]!=S->ProcIndexBuffer[I+2])return nullptr;
    return new FMWLineProxy(this);
}
