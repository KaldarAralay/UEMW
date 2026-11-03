#include "MWUI.h"
#include "MWLive.h"
#include "MWFrame.h"
#include "MWChannel.h"
#include "Async/Async.h"
#include "Engine/Texture2D.h"
#include "TextureResource.h"
#include "CanvasItem.h"
#include "RenderUtils.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/CoreDelegates.h"
#include "Misc/ScopeLock.h"
#include "RenderingThread.h"
#include "ProfilingDebugging/CpuProfilerTrace.h"
#include "HAL/PlatformProcess.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"


namespace {
double UIClock(){return (FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds();}
bool Hex(const FString& S,int32 N){if(S.Len()!=N)return false;for(TCHAR C:S)if(!FChar::IsHexDigit(C) || FChar::IsUpper(C))return false;return true;}
bool Integer(const TSharedPtr<FJsonObject>& J,const TCHAR* Key,double Min,double Max,double& Out){return J->TryGetNumberField(Key,Out) && FMath::IsFinite(Out) && Out>=Min && Out<=Max && Out==FMath::FloorToDouble(Out);}
bool Bytes(const FString& Path,int64 Size,TArray<uint8>& Out){return Size>0 && IFileManager::Get().FileSize(*Path)==Size && FFileHelper::LoadFileToArray(Out,*Path) && Out.Num()==Size;}
}
bool MWUIFresh(const FMWUIFrame& F,uint32 Pid,const FString& Session,double Now){return F.Valid && F.Pid==Pid && F.Session==Session && Now>=F.Stamp && Now-F.Stamp<=.5;}
FMWUIFramePtr MWReadUI(const FString& Root,const TSet<FString>& Known,const FString* Manifest,const TArray<uint8>* SharedBody,const FMWChannelReader* Channel) {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_ReadNativeUI);
    const double Began=FPlatformTime::Seconds();double Part=Began;
    if(!Manifest) {
        const double Started=UIClock();FMWChannelReader Local;FString Text;TArray<uint8> Body;bool Shared=false;
        if(Local.Read(Root/TEXT("local/bridge/ui.json"),Text,Body,Shared)!=EMWChannelRead::Ready){auto F=MakeShared<FMWUIFrame,ESPMode::ThreadSafe>();F->Error=TEXT("waiting for native UI");return F;}
        const double FetchMs=(FPlatformTime::Seconds()-Began)*1000;
        auto F=MWReadUI(Root,Known,&Text,Shared?&Body:nullptr,Shared?&Local:nullptr);F->ReadStarted=Started;F->ReadParts[4]+=FetchMs;return F;
    }
    auto Out=MakeShared<FMWUIFrame,ESPMode::ThreadSafe>();Out->ReadStarted=UIClock();Out->Error=TEXT("waiting for native UI");
    FString Text,Protocol,Status;TSharedPtr<FJsonObject> J;double Version=0,Pid=0,Sequence=0,Stamp=0,W=0,H=0,Draws=0;
    const bool Read=Manifest?(Text=*Manifest,Text.Len()<=32768):MWReadSnapshot(Root/TEXT("local/bridge/ui.json"),Text,32768);
    if(!Read || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),J) || !J.IsValid() ||
       !J->TryGetStringField(TEXT("protocol"),Protocol) || Protocol!=TEXT("uemw.ui") || !J->TryGetNumberField(TEXT("version"),Version) || (Version!=1 && Version!=2) ||
       !J->TryGetStringField(TEXT("status"),Status) || Status!=TEXT("live")){if(J.IsValid())J->TryGetStringField(TEXT("error"),Out->Error);return Out;}
    if(Version==2 && (!SharedBody || !Channel || !Channel->Matches(J)))return Out;
    Out->Error=TEXT("invalid native UI frame");FGuid Session;
    if(!Integer(J,TEXT("pid"),1,MAX_uint32,Pid) || !J->TryGetStringField(TEXT("session"),Out->Session) || !FGuid::Parse(Out->Session,Session) ||
       !Integer(J,TEXT("sequence"),0,9007199254740991.,Sequence) || !J->TryGetNumberField(TEXT("sample_unix_ns"),Stamp) || !FMath::IsFinite(Stamp) || Stamp<=0 ||
       !Integer(J,TEXT("width"),320,8192,W) || !Integer(J,TEXT("height"),200,8192,H) || !Integer(J,TEXT("draws"),0,2048,Draws))return Out;
    const TSharedPtr<FJsonObject>* UI=nullptr;const TArray<TSharedPtr<FJsonValue>>* Menus=nullptr;
    const TSharedPtr<FJsonObject>* Timing=nullptr;
    if(J->TryGetObjectField(TEXT("timing"),Timing) && Timing->IsValid()) {
        auto ReadTime=[&](const TCHAR* Key,double& Value){double N=0;if((*Timing)->TryGetNumberField(Key,N) && FMath::IsFinite(N) && N>0)Value=N/1e9;};
        ReadTime(TEXT("capture_end_ns"),Out->CaptureEnd);ReadTime(TEXT("encoded_ns"),Out->Encoded);ReadTime(TEXT("body_ready_ns"),Out->BodyReady);ReadTime(TEXT("maintenance_end_ns"),Out->MaintenanceEnd);ReadTime(TEXT("publish_begin_ns"),Out->PublishBegin);
    }
    if(!J->TryGetObjectField(TEXT("ui"),UI) || !UI->IsValid() || !(*UI)->TryGetBoolField(TEXT("native_ui"),Out->NativeMenu) || !(*UI)->TryGetArrayField(TEXT("active_menus"),Menus) || Menus->Num()>256)return Out;
    for(const auto& V:*Menus){FString Name;if(!V->TryGetString(Name) || Name.IsEmpty() || Name.Len()>96 || Out->Menus.Contains(Name))return Out;Out->Menus.Add(Name);}Out->Menus.Sort();
    const TArray<TSharedPtr<FJsonValue>>* Regions=nullptr;
    if(J->HasField(TEXT("native_regions"))) {
        if(!J->TryGetArrayField(TEXT("native_regions"),Regions) || Regions->Num()>16)return Out;
        for(const auto& V:*Regions) {
            const TSharedPtr<FJsonObject>* R=nullptr;const TArray<TSharedPtr<FJsonValue>>* Rect=nullptr;FString Kind,Menu;double N[4];
            if(!V->TryGetObject(R) || !R->IsValid() || !(*R)->TryGetStringField(TEXT("kind"),Kind) || Kind!=TEXT("original-ui-render-target") || !(*R)->TryGetStringField(TEXT("menu"),Menu) || (Menu!=TEXT("MenuInventory") && Menu!=TEXT("MenuMap")) || !Out->Menus.Contains(Menu) || !(*R)->TryGetArrayField(TEXT("rect"),Rect) || Rect->Num()!=4)return Out;
            for(int32 I=0;I<4;++I)if(!(*Rect)[I]->TryGetNumber(N[I]) || !FMath::IsFinite(N[I]))return Out;
            if(N[0]<0 || N[1]<0 || N[2]>W || N[3]>H || N[0]>=N[2] || N[1]>=N[3])return Out;
            Out->NativeRegions.Add(FVector4d(N[0],N[1],N[2],N[3]));
        }
    }
    const TArray<TSharedPtr<FJsonValue>>* Textures=nullptr;int64 ImageBytes=0;
    Out->ReadParts[0]=(FPlatformTime::Seconds()-Part)*1000;Part=FPlatformTime::Seconds();
    if(!J->TryGetArrayField(TEXT("textures"),Textures) || Textures->Num()>128)return Out;
    for(const auto& V:*Textures) {
        const TSharedPtr<FJsonObject>* Row=nullptr;FMWUITexture T;FString SHA;double Width=0,Height=0,Size=0;
        if(!V->TryGetObject(Row) || !Row->IsValid() || !(*Row)->TryGetStringField(TEXT("sha256"),SHA) || !Hex(SHA,64) || !(*Row)->TryGetStringField(TEXT("file"),T.Name) || T.Name!=SHA+TEXT(".utx") ||
           !(*Row)->TryGetStringField(TEXT("md5"),T.Digest) || !Hex(T.Digest,32) || !Integer(*Row,TEXT("width"),1,1024,Width) || !Integer(*Row,TEXT("height"),1,1024,Height) || !Integer(*Row,TEXT("bytes"),16,4194316,Size) || Size!=12+Width*Height*4)return Out;
        T.Width=int32(Width);T.Height=int32(Height);ImageBytes+=int64(Size);if(ImageBytes>64ll*1024*1024)return Out;
        if(!Known.Contains(T.Name+TEXT("|")+T.Digest)) {
            TArray<uint8> Raw;if(!Bytes(Root/TEXT("local/ui-assets")/T.Name,int64(Size),Raw) || FMemory::Memcmp(Raw.GetData(),"UTX1",4) || !FMD5::HashBytes(Raw.GetData(),Raw.Num()).Equals(T.Digest,ESearchCase::IgnoreCase))return Out;
            uint32 TW=0,TH=0;FMemory::Memcpy(&TW,Raw.GetData()+4,4);FMemory::Memcpy(&TH,Raw.GetData()+8,4);if(TW!=T.Width || TH!=T.Height)return Out;
            T.Pixels.Append(Raw.GetData()+12,Raw.Num()-12);for(int32 I=0;I<T.Pixels.Num();I+=4)Swap(T.Pixels[I],T.Pixels[I+2]); // Original RGBA to UE BGRA.
        }
        Out->Textures.Add(MoveTemp(T));
    }
    const TSharedPtr<FJsonObject>* Ref=nullptr;FString Name,Digest;double Size=0;
    Out->ReadParts[1]=(FPlatformTime::Seconds()-Part)*1000;Part=FPlatformTime::Seconds();
    if(!J->TryGetObjectField(TEXT("frame_ref"),Ref) || !Ref->IsValid() || !(*Ref)->TryGetStringField(TEXT("file"),Name) ||
       Name!=TEXT("ui-frames/")+Session.ToString(EGuidFormats::Digits).ToLower()+TEXT("-")+FString::Printf(TEXT("%lld"),int64(Sequence))+TEXT(".uui") ||
       !(*Ref)->TryGetStringField(TEXT("md5"),Digest) || !Hex(Digest,32) || !Integer(*Ref,TEXT("bytes"),56,2*1024*1024,Size))return Out;
    TArray<uint8> FileBody;
    if(Version==1 && !Bytes(Root/TEXT("local/bridge")/Name,int64(Size),FileBody))return Out;
    const TArray<uint8>& Raw=Version==2?*SharedBody:FileBody;
    if(Raw.Num()!=int64(Size) || !FMD5::HashBytes(Raw.GetData(),Raw.Num()).Equals(Digest,ESearchCase::IgnoreCase) || FMemory::Memcmp(Raw.GetData(),"UUI1",4) || Raw[4]!=1 || Raw[5] || Raw[6] || Raw[7])return Out;
    FGuid BodySession;uint64 BodySequence=0;double BodyStamp=0;uint32 Fields[4];FMemory::Memcpy(&BodySession,Raw.GetData()+8,16);FMemory::Memcpy(&BodySequence,Raw.GetData()+24,8);FMemory::Memcpy(&BodyStamp,Raw.GetData()+32,8);FMemory::Memcpy(Fields,Raw.GetData()+40,16);
    if(BodySession!=Session || BodySequence!=uint64(Sequence) || BodyStamp!=Stamp || Fields[0]!=uint32(Pid) || Fields[1]!=uint32(W) || Fields[2]!=uint32(H) || Fields[3]!=uint32(Draws))return Out;
    int32 Offset=56,TotalIndices=0;
    Out->ReadParts[2]=(FPlatformTime::Seconds()-Part)*1000;Part=FPlatformTime::Seconds();
    for(uint32 I=0;I<Fields[3];++I) {
        uint32 D[4];if(Offset>Raw.Num()-16)return Out;FMemory::Memcpy(D,Raw.GetData()+Offset,16);Offset+=16;
        if(!D[0] || D[0]>=0xfff00000 || (D[1]!=MAX_uint32 && D[1]>=uint32(Out->Textures.Num())) || !D[2] || D[2]>65536 || !D[3] || D[3]>196608 || D[3]%3)return Out;
        Out->Vertices+=D[2];TotalIndices+=D[3];if(Out->Vertices>65536 || TotalIndices>196608 || int64(Offset)+int64(D[2])*20+int64(D[3])*2>Raw.Num())return Out;
        struct Vertex {FVector2D P,UV;FLinearColor C;};TArray<Vertex> Vertices;Vertices.SetNum(D[2]);
        for(uint32 K=0;K<D[2];++K) {
            float Values[4];FMemory::Memcpy(Values,Raw.GetData()+Offset,16);for(float N:Values)if(!FMath::IsFinite(N) || FMath::Abs(N)>1e7)return Out;
            auto& V=Vertices[K];V.P=FVector2D(Values[0],Values[1]);V.UV=FVector2D(Values[2],Values[3]);
            const uint8* C=Raw.GetData()+Offset+16;V.C=FLinearColor(C[0]/255.f,C[1]/255.f,C[2]/255.f,C[3]/255.f);Offset+=20;
        }
        FMWUIDraw Draw;Draw.Id=D[0];Draw.Texture=D[1];Draw.Triangles.Reserve(D[3]/3);
        for(uint32 K=0;K<D[3];K+=3) {
            uint16 Indices[3];FMemory::Memcpy(Indices,Raw.GetData()+Offset,6);Offset+=6;for(uint16 Index:Indices)if(Index>=D[2])return Out;
            const auto& A=Vertices[Indices[0]];const auto& B=Vertices[Indices[1]];const auto& C=Vertices[Indices[2]];FCanvasUVTri T;
            T.V0_Pos=A.P;T.V1_Pos=B.P;T.V2_Pos=C.P;T.V0_UV=A.UV;T.V1_UV=B.UV;T.V2_UV=C.UV;T.V0_Color=A.C;T.V1_Color=B.C;T.V2_Color=C.C;Draw.Triangles.Add(T);
        }
        Out->Draws.Add(MoveTemp(Draw));
    }
    if(Offset!=Raw.Num())return Out;
    Out->ReadParts[3]=(FPlatformTime::Seconds()-Part)*1000;
    Out->Pid=uint32(Pid);Out->Sequence=int64(Sequence);Out->Stamp=Stamp/1e9;Out->Width=int32(W);Out->Height=int32(H);Out->Digest=Digest;Out->ReadFinished=UIClock();Out->Error.Empty();Out->Valid=true;return Out;
}
FMWUIReader::FMWUIReader(const FString& InRoot):Root(InRoot){Worker=Async(EAsyncExecution::Thread,[this](){Run();});}
FMWUIReader::~FMWUIReader(){Stop=true;if(Worker.IsValid())Worker.Wait();}
void FMWUIReader::Configure(const TSet<FString>& Value){FScopeLock Guard(&Mutex);Known=Value;++Revision;}
bool FMWUIReader::Take(FMWUIFramePtr& Out){FScopeLock Guard(&Mutex);if(!Ready)return false;Out=MoveTemp(Pending);Ready=false;return true;}
void FMWUIReader::Run() {
    FString Last;TArray<uint8> LastBody;bool LastShared=false;FMWChannelReader Channel;uint64 SeenRevision=MAX_uint64;
    while(!Stop) {
        const double Started=UIClock(),ReadBegan=FPlatformTime::Seconds();FString Text;TArray<uint8> Body;bool Shared=false;
        const auto Status=Channel.Read(Root/TEXT("local/bridge/ui.json"),Text,Body,Shared);
        if(Status==EMWChannelRead::Invalid || Status==EMWChannelRead::Busy){FPlatformProcess::Sleep(.002f);continue;}
        const double ManifestLoaded=FPlatformTime::Seconds();TSet<FString> Images;uint64 Current=0;
        {FScopeLock Guard(&Mutex);Current=Revision;if((Status==EMWChannelRead::Ready && Text!=Last) || Current!=SeenRevision)Images=Known;}
        if((Status==EMWChannelRead::Unchanged || Text==Last) && Current==SeenRevision){FPlatformProcess::Sleep(.002f);continue;}
        // Texture acknowledgments may require decoding the same owned frame
        // again. Keep its original stamp; an unchanged slot never renews it.
        if(Status==EMWChannelRead::Unchanged){Text=Last;Shared=LastShared;}
        const double HeaderExtra=(FPlatformTime::Seconds()-ReadBegan)*1000;
        const auto& OwnedBody=Status==EMWChannelRead::Unchanged?LastBody:Body;
        auto Frame=MWReadUI(Root,Images,&Text,Shared?&OwnedBody:nullptr,Shared?&Channel:nullptr);Frame->ReadParts[4]=(ManifestLoaded-ReadBegan)*1000;Frame->ReadParts[5]=HeaderExtra-Frame->ReadParts[4];Frame->ReadQueued=Frame->ReadStarted=Started;
        if(Status==EMWChannelRead::Ready){LastBody=MoveTemp(Body);LastShared=Shared;}
        Last=MoveTemp(Text);SeenRevision=Current;
        // One owned latest slot, never a decoded-frame backlog.
        {FScopeLock Guard(&Mutex);Pending=MoveTemp(Frame);Ready=true;}
    }
}
void FMWUIView::Update(AMWLive& O) {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_UpdateNativeUI);
    const double Now=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds(),Tick=FPlatformTime::Seconds();O.UIReady=false;
    if(!O.SourcePid || O.Session.IsEmpty())return;
    if(O.PresentationSamples && !Statistics){Statistics=MakeShared<FMWUIStatistics,ESPMode::ThreadSafe>();EndFrameHandle=FCoreDelegates::OnEndFrame.AddRaw(this,&FMWUIView::EndFrame);}
    static const bool Legacy=FParse::Param(FCommandLine::Get(),TEXT("UEMWUILegacyReader")) || FPlatformMisc::GetEnvironmentVariable(TEXT("UEMW_UI_LEGACY_READER"))==TEXT("1");
    if(!Legacy && !Reader && Tick>=NextRead)Reader=new FMWUIReader(O.DataRoot);
    if(Reader && SentTextureRevision!=TextureRevision) {
        TSet<FString> Known;for(const auto& Pair:Digests)if(O.UITextures.Contains(Pair.Key))Known.Add(Pair.Key+TEXT("|")+Pair.Value);
        Reader->Configure(Known);SentTextureRevision=TextureRevision;
    }
    FMWUIFramePtr Latest;
    if(Reader && Reader->Take(Latest)) {
        if(Latest.IsValid() && MWUIFresh(*Latest,O.SourcePid,O.Session,Now)){Pending=Latest;UploadIndex=0;}else if(Latest.IsValid())O.UIStatus=Latest->Error;
    }
    if(Legacy && Future.IsValid() && Future.IsReady()) {
        auto Incoming=Future.Get();Future.Reset();
        if(Incoming.IsValid() && MWUIFresh(*Incoming,O.SourcePid,O.Session,Now)){Pending=Incoming;UploadIndex=0;}else if(Incoming.IsValid())O.UIStatus=Incoming->Error;
    }
    if(Legacy && !Future.IsValid() && Tick>=NextRead) {
        TSet<FString> Known;for(const auto& Pair:Digests)if(O.UITextures.Contains(Pair.Key))Known.Add(Pair.Key+TEXT("|")+Pair.Value);
        const FString Root=O.DataRoot;const double Queued=UIClock();Future=Async(EAsyncExecution::ThreadPool,[Root,Queued,Known=MoveTemp(Known)](){auto Result=MWReadUI(Root,Known);Result->ReadQueued=Queued;return Result;});NextRead=Tick+.025;
    }
    if(Pending.IsValid()) {
        if(!MWUIFresh(*Pending,O.SourcePid,O.Session,Now))Pending.Reset();
        else {
            const double Began=FPlatformTime::Seconds();int32 Uploads=0;
            while(UploadIndex<Pending->Textures.Num()) {
                auto& T=Pending->Textures[UploadIndex++];Used.Add(T.Name,Tick);
                if(Digests.FindRef(T.Name)==T.Digest && O.UITextures.Contains(T.Name))continue;
                if(T.Pixels.Num()!=T.Width*T.Height*4){O.UIStatus=TEXT("native UI image not ready");Pending.Reset();break;}
                // Retire only inactive cached images. Current and pending frames
                // can each own at most 64 MiB; the GPU cache is capped at 128 MiB.
                TSet<FString> Protected;for(const auto& Image:Pending->Textures)Protected.Add(Image.Name);if(Frame.IsValid())for(const auto& Image:Frame->Textures)Protected.Add(Image.Name);
                for(auto It=O.UITextures.CreateIterator();It;++It)if(!Protected.Contains(It.Key()) && (O.UITextures.Num()>192 || Tick-Used.FindRef(It.Key())>30)){Digests.Remove(It.Key());Used.Remove(It.Key());It.RemoveCurrent();++TextureRevision;}
                int64 BytesUsed=0;for(const auto& Pair:O.UITextures)BytesUsed+=int64(Pair.Value->GetSizeX())*Pair.Value->GetSizeY()*4;
                if(BytesUsed+T.Pixels.Num()>128ll*1024*1024){O.UIStatus=TEXT("native UI GPU cache budget exhausted");Pending.Reset();break;}
                const double UploadBegan=FPlatformTime::Seconds(),UploadStarted=UIClock();
                auto* Texture=UTexture2D::CreateTransient(T.Width,T.Height,PF_B8G8R8A8);if(!Texture){Pending.Reset();break;}
                Texture->SRGB=true;Texture->NeverStream=true;Texture->Filter=TF_Bilinear;Texture->AddressX=Texture->AddressY=TA_Clamp;
                auto& Mip=Texture->GetPlatformData()->Mips[0];Mip.BulkData.Lock(LOCK_READ_WRITE);void* Pixels=Mip.BulkData.Realloc(T.Pixels.Num());FMemory::Memcpy(Pixels,T.Pixels.GetData(),T.Pixels.Num());Mip.BulkData.Unlock();Texture->UpdateResource();O.UITextures.Add(T.Name,Texture);Digests.Add(T.Name,T.Digest);T.Pixels.Empty();++TextureRevision;
                if(Statistics){FScopeLock Guard(&Statistics->Lock);if(Statistics->Images.Num()<256)Statistics->Images.Add({Pending->Session,T.Name,Pending->Sequence,int64(T.Width)*T.Height*4,UploadStarted,UIClock(),(FPlatformTime::Seconds()-UploadBegan)*1000});else ++Statistics->ImageOverflow;}
                if(++Uploads>=8 || FPlatformTime::Seconds()-Began>.002)break;
            }
            if(Pending.IsValid() && UploadIndex==Pending->Textures.Num()){Pending->Promoted=UIClock();Frame=Pending;Pending.Reset();}
        }
    }
    if(Frame.IsValid() && MWUIFresh(*Frame,O.SourcePid,O.Session,Now)) {
        O.UIReady=true;O.UIStamp=Frame->Stamp;O.UISequence=Frame->Sequence;O.UIStatus=Frame->NativeRegions.Num()?TEXT("native UI geometry / original UI target regions"):TEXT("native menu-camera geometry");O.UIMenus=Frame->Menus;O.UINativeMenu=Frame->NativeMenu;O.UIDraws=Frame->Draws.Num();O.UIRegions=Frame->NativeRegions;O.UIWidth=Frame->Width;O.UIHeight=Frame->Height;
    }else O.UIDraws=0;
}
bool FMWUIView::Draw(AMWLive& O,UCanvas* Canvas) {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_DrawNativeUI);
    const double Now=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds();
    if(!Canvas || !O.UIReady || !Frame.IsValid() || !MWUIFresh(*Frame,O.SourcePid,O.Session,Now))return false;
    if(O.PresentationSamples && !Statistics){Statistics=MakeShared<FMWUIStatistics,ESPMode::ThreadSafe>();EndFrameHandle=FCoreDelegates::OnEndFrame.AddRaw(this,&FMWUIView::EndFrame);}
    const double DrawStart=UIClock();
    const double Scale=FMath::Min(double(Canvas->SizeX)/Frame->Width,double(Canvas->SizeY)/Frame->Height);
    const FVector2D Origin((Canvas->SizeX-Frame->Width*Scale)*.5,(Canvas->SizeY-Frame->Height*Scale)*.5);
    for(const auto& D:Frame->Draws) {
        UTexture2D* Texture=D.Texture==MAX_uint32?nullptr:O.UITextures.FindRef(Frame->Textures[D.Texture].Name);if(D.Texture!=MAX_uint32 && !Texture)return false;
        TArray<FCanvasUVTri> Triangles=D.Triangles;for(auto& T:Triangles){T.V0_Pos=T.V0_Pos*Scale+Origin;T.V1_Pos=T.V1_Pos*Scale+Origin;T.V2_Pos=T.V2_Pos*Scale+Origin;}
        FCanvasTriangleItem Item(Triangles,Texture?Texture->GetResource():GWhiteTexture);Item.BlendMode=SE_BLEND_Translucent;Canvas->DrawItem(Item);
    }
    if(Statistics) {
        DrawStat.Session=Frame->Session;DrawStat.Digest=Frame->Digest;DrawStat.Sequence=Frame->Sequence;DrawStat.GameFrame=GFrameCounter;
        const double Values[]={Frame->Stamp,Frame->CaptureEnd,Frame->Encoded,Frame->BodyReady,Frame->MaintenanceEnd,Frame->PublishBegin,Frame->ReadQueued,Frame->ReadStarted,Frame->ReadFinished,Frame->Promoted,DrawStart,UIClock(),0,0,0};
        FMemory::Memcpy(DrawStat.Times,Values,sizeof(Values));HaveDrawStat=true;
        FMemory::Memcpy(DrawStat.ReadParts,Frame->ReadParts,sizeof(DrawStat.ReadParts));
    }
    return true;
}

FMWUIView::~FMWUIView(){if(EndFrameHandle.IsValid())FCoreDelegates::OnEndFrame.Remove(EndFrameHandle);delete Reader;Reader=nullptr;if(Future.IsValid())Future.Wait();}
void FMWUIView::EndFrame() {
    if(!HaveDrawStat || !Statistics)return;HaveDrawStat=false;auto Row=MoveTemp(DrawStat);Row.Times[12]=UIClock();auto Stats=Statistics.ToSharedRef();
    ENQUEUE_RENDER_COMMAND(UEMWNativeUIDrawTiming)([Stats,Row=MoveTemp(Row)](FRHICommandListImmediate&)mutable{
        Row.Times[13]=UIClock();Row.Times[14]=double(GFrameNumberRenderThread);
        FScopeLock Guard(&Stats->Lock);if(Stats->Rows.Num()<256)Stats->Rows.Add(MoveTemp(Row));else ++Stats->Overflow;
    });
}
void FMWUIStatistics::Export(const TSharedPtr<FJsonObject>& Json) {
    TArray<FMWUIStatRow> Taken;TArray<FMWUIImageStat> Uploaded;uint32 Dropped=0,ImageDropped=0;{FScopeLock Guard(&Lock);Swap(Taken,Rows);Swap(Uploaded,Images);Dropped=Overflow;Overflow=0;ImageDropped=ImageOverflow;ImageOverflow=0;}
    TArray<TSharedPtr<FJsonValue>> Values;
    for(const auto& R:Taken){auto J=MakeShared<FJsonObject>();J->SetStringField(TEXT("session"),R.Session);J->SetStringField(TEXT("md5"),R.Digest);J->SetNumberField(TEXT("sequence"),R.Sequence);J->SetNumberField(TEXT("game_frame"),R.GameFrame);TArray<TSharedPtr<FJsonValue>> T;for(double V:R.Times)T.Add(MakeShared<FJsonValueNumber>(V));J->SetArrayField(TEXT("times"),T);T.Empty();for(double V:R.ReadParts)T.Add(MakeShared<FJsonValueNumber>(V));J->SetArrayField(TEXT("read_parts_ms"),T);Values.Add(MakeShared<FJsonValueObject>(J));}
    Json->SetArrayField(TEXT("ui_pipeline"),Values);Json->SetNumberField(TEXT("ui_pipeline_overflow"),Dropped);
    Values.Empty();for(const auto& R:Uploaded){auto J=MakeShared<FJsonObject>();J->SetStringField(TEXT("session"),R.Session);J->SetStringField(TEXT("image"),R.Image);J->SetNumberField(TEXT("sequence"),R.Sequence);J->SetNumberField(TEXT("bytes"),R.Bytes);J->SetNumberField(TEXT("started"),R.Started);J->SetNumberField(TEXT("queued"),R.Queued);J->SetNumberField(TEXT("cpu_ms"),R.CpuMs);Values.Add(MakeShared<FJsonValueObject>(J));}
    Json->SetArrayField(TEXT("ui_image_resources"),Values);Json->SetNumberField(TEXT("ui_image_resources_overflow"),ImageDropped);Json->SetStringField(TEXT("ui_image_resource_scope"),TEXT("CPU texture construction/copy and UpdateResource enqueue; not GPU upload completion"));
}
