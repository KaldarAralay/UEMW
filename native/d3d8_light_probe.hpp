#pragma once
// Optional read-only draw-state probe for a separately built d3d8to9 shim.
// Never included by the normal client or launcher. Capture exactly one frame
// only when uemw-light-probe.request exists beside the PRIVATE game executable.
#include <cstdio>
#include <cmath>
#include <cstring>
#include <string>
namespace UEMWLightProbe {
static FILE* File=nullptr;
static unsigned Draws=0;
static std::wstring Path(const wchar_t* Name) {
    wchar_t Exe[32768];const DWORD Count=GetModuleFileNameW(nullptr,Exe,32768);
    if(!Count || Count>=32768)return {};
    std::wstring Result(Exe,Count);const auto Slash=Result.find_last_of(L"\\/");
    if(Slash==std::wstring::npos)return {};
    return Result.substr(0,Slash+1)+Name;
}
static void Present() {
    if(File){fclose(File);File=nullptr;}
    const auto Request=Path(L"uemw-light-probe.request");
    if(Request.empty() || GetFileAttributesW(Request.c_str())==INVALID_FILE_ATTRIBUTES)return;
    const auto Output=Path(L"uemw-light-probe.jsonl");
    if(!DeleteFileW(Request.c_str()))return;
    _wfopen_s(&File,Output.c_str(),L"wb");Draws=0;
}
static void Floats(const float* Values,unsigned Count) {
    fputc('[',File);for(unsigned I=0;I<Count;++I){if(I)fputc(',',File);if(std::isfinite(Values[I]))fprintf(File,"%.9g",Values[I]);else fprintf(File,"null");}fputc(']',File);
}
static void Draw(IDirect3DDevice9* Device,unsigned Type,int Base,unsigned Min,unsigned Vertices,unsigned Start,unsigned Primitives) {
    if(!File || Draws++>=4096)return;
    D3DMATRIX World={};D3DMATERIAL9 Material={};Device->GetTransform(D3DTS_WORLD,&World);Device->GetMaterial(&Material);
    fprintf(File,"{\"draw\":%u,\"type\":%u,\"base\":%d,\"min\":%u,\"vertices\":%u,\"start\":%u,\"primitives\":%u,\"world\":",Draws,Type,Base,Min,Vertices,Start,Primitives);Floats(&World._11,16);
    fprintf(File,",\"material\":");Floats(&Material.Diffuse.r,17);
    const D3DRENDERSTATETYPE States[]={D3DRS_LIGHTING,D3DRS_COLORVERTEX,D3DRS_DIFFUSEMATERIALSOURCE,D3DRS_AMBIENTMATERIALSOURCE,D3DRS_EMISSIVEMATERIALSOURCE,D3DRS_SPECULARMATERIALSOURCE,D3DRS_AMBIENT,D3DRS_SPECULARENABLE,D3DRS_SRGBWRITEENABLE,D3DRS_NORMALIZENORMALS,D3DRS_SHADEMODE};
    fprintf(File,",\"states\":{");bool First=true;
    for(auto State:States){DWORD Value=0;const HRESULT H=Device->GetRenderState(State,&Value);if(SUCCEEDED(H)){fprintf(File,First?"\"%u\":%u":",\"%u\":%u",unsigned(State),Value);First=false;}}
    fprintf(File,"},\"stages\":[");
    for(unsigned Stage=0;Stage<3;++Stage){if(Stage)fputc(',',File);fprintf(File,"[");for(auto State:{D3DTSS_COLOROP,D3DTSS_COLORARG1,D3DTSS_COLORARG2,D3DTSS_ALPHAOP}){DWORD Value=0;Device->GetTextureStageState(Stage,State,&Value);fprintf(File,State==D3DTSS_COLOROP?"%u":",%u",Value);}fprintf(File,"]");}
    fprintf(File,"],\"lights\":[");First=true;
    for(unsigned I=0;I<128;++I){BOOL Enabled=FALSE;D3DLIGHT9 Light={};if(FAILED(Device->GetLightEnable(I,&Enabled)) || !Enabled || FAILED(Device->GetLight(I,&Light)))continue;fprintf(File,First?"{\"index\":%u,\"type\":%u,\"data\":":" ,{\"index\":%u,\"type\":%u,\"data\":",I,unsigned(Light.Type));Floats(&Light.Diffuse.r,25);fputc('}',File);First=false;}
    fprintf(File,"],\"vertex_sample\":[");
    IDirect3DVertexDeclaration9* Decl=nullptr;D3DVERTEXELEMENT9 Elements[MAXD3DDECLLENGTH];UINT Count=MAXD3DDECLLENGTH;
    int Position=-1,Normal=-1,Colour=-1;
    if(SUCCEEDED(Device->GetVertexDeclaration(&Decl)) && Decl){if(SUCCEEDED(Decl->GetDeclaration(Elements,&Count)))for(UINT I=0;I<Count;++I){const auto& E=Elements[I];if(E.Stream)continue;if(E.Usage==D3DDECLUSAGE_POSITION && E.Type==D3DDECLTYPE_FLOAT3)Position=E.Offset;if(E.Usage==D3DDECLUSAGE_NORMAL && E.Type==D3DDECLTYPE_FLOAT3)Normal=E.Offset;if(E.Usage==D3DDECLUSAGE_COLOR && E.UsageIndex==0 && E.Type==D3DDECLTYPE_D3DCOLOR)Colour=E.Offset;}Decl->Release();}
    IDirect3DVertexBuffer9* Buffer=nullptr;UINT Offset=0,Stride=0;HRESULT LockResult=E_FAIL;D3DVERTEXBUFFER_DESC Desc={};
    if(SUCCEEDED(Device->GetStreamSource(0,&Buffer,&Offset,&Stride)) && Buffer){Buffer->GetDesc(&Desc);const unsigned N=(Vertices<16?Vertices:16);const long long StartByte=static_cast<long long>(Offset)+(static_cast<long long>(Base)+Min)*Stride;void* Bytes=nullptr;
        if(Stride && Stride<=256 && StartByte>=0 && StartByte+N*Stride<=Desc.Size)LockResult=Buffer->Lock(UINT(StartByte),N*Stride,&Bytes,D3DLOCK_READONLY);
        if(SUCCEEDED(LockResult)){for(unsigned I=0;I<N;++I){const auto* B=static_cast<const unsigned char*>(Bytes)+I*Stride;if(I)fputc(',',File);fprintf(File,"{\"p\":");if(Position>=0 && Position+12<=int(Stride))Floats(reinterpret_cast<const float*>(B+Position),3);else fprintf(File,"null");fprintf(File,",\"n\":");if(Normal>=0 && Normal+12<=int(Stride))Floats(reinterpret_cast<const float*>(B+Normal),3);else fprintf(File,"null");DWORD C=0;if(Colour>=0 && Colour+4<=int(Stride))memcpy(&C,B+Colour,4);fprintf(File,",\"c\":%lu}",static_cast<unsigned long>(C));}Buffer->Unlock();}Buffer->Release();}
    fprintf(File,"],\"vertex_stream\":[%u,%u,%u,%u,%u,%ld]}\n",Offset,Stride,Desc.Usage,Desc.FVF,unsigned(Desc.Pool),static_cast<long>(LockResult));
}
}
