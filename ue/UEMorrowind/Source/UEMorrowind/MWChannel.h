#pragma once
#include "CoreMinimal.h"
class FJsonObject;
enum class EMWChannelRead {Ready,Unchanged,Busy,Invalid};
// Read-only mapping; no shared view or JSON crosses into the game thread.
class FMWChannelReader {
public:
    ~FMWChannelReader(){Close();}
    EMWChannelRead Read(const FString& Path,FString& Text,TArray<uint8>& Body,bool& Shared);
    bool Matches(const TSharedPtr<FJsonObject>& Packet) const;
private:
    void Close();
    void* Mapping=nullptr;void* Mutex=nullptr;void* Writer=nullptr;
    const uint8* View=nullptr;
    FGuid Session,Nonce;
    uint32 NativePid=0,WriterPid=0;
    uint32 BodyBytes=0;
    uint64 Generation=0;
    FString BodyDigest;
};
