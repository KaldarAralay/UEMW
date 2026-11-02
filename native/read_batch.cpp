// x64 bridge-local ABI v1. Loaded by Python, never injected into Morrowind.
#define WIN32_LEAN_AND_MEAN
#include <Windows.h>
#include <cstdint>

struct ReadRange { uint32_t address,bytes,offset; };
struct ReadResult { uint32_t bytes,error; };
static_assert(sizeof(void*)==8,"Build the external bridge helper for x64");
static_assert(sizeof(ReadRange)==12 && sizeof(ReadResult)==8,"ABI v1 layout");

extern "C" __declspec(dllexport) uint32_t WINAPI UEMWReadBatchVersion() {return 1;}

extern "C" __declspec(dllexport) uint32_t WINAPI UEMWReadBatch(
    HANDLE process,const ReadRange* ranges,uint32_t count,
    uint8_t* destination,uint32_t capacity,ReadResult* results) {
    if(!process || !ranges || !destination || !results || !count || count>32768 || !capacity || capacity>32*1024*1024)
        return ERROR_INVALID_PARAMETER;
    // Validate the entire descriptor table before touching the source process.
    for(uint32_t i=0;i<count;++i) {
        const auto& r=ranges[i];
        if(r.address<0x10000 || r.address>=0xfff00000 || !r.bytes || r.bytes>4*1024*1024 ||
            uint64_t(r.address)+r.bytes>0xfff00000 || r.offset>capacity || r.bytes>capacity-r.offset)
            return ERROR_INVALID_PARAMETER;
    }
    for(uint32_t i=0;i<count;++i) {
        const auto& r=ranges[i];SIZE_T got=0;
        const BOOL ok=ReadProcessMemory(process,reinterpret_cast<const void*>(uintptr_t(r.address)),destination+r.offset,r.bytes,&got);
        results[i].bytes=static_cast<uint32_t>(got);
        results[i].error=ok && got==r.bytes ? ERROR_SUCCESS : (ok ? ERROR_PARTIAL_COPY : GetLastError());
        if(!ok && !results[i].error)results[i].error=ERROR_PARTIAL_COPY;
    }
    return ERROR_SUCCESS;
}
