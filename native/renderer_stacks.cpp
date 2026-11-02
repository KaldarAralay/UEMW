// Local UE-only hang diagnosis. No debugger attachment, injection or game access.
// Each UE thread is resumed immediately after capturing its register context.
#include <windows.h>
#include <tlhelp32.h>
#include <dbghelp.h>
#include <cstdio>
#include <cwchar>

int wmain(int argc,wchar_t** argv) {
    if(argc!=2)return 2;
    const DWORD pid=wcstoul(argv[1],nullptr,10);
    HANDLE process=OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,FALSE,pid);
    if(!process)return 3;
    wchar_t path[32768];DWORD length=32768;
    if(!QueryFullProcessImageNameW(process,0,path,&length) ||
       !wcsrchr(path,L'\\') || _wcsicmp(wcsrchr(path,L'\\')+1,L"UnrealEditor.exe")) {
        CloseHandle(process);return 4;
    }
    SymSetOptions(SYMOPT_DEFERRED_LOADS|SYMOPT_UNDNAME|SYMOPT_FAIL_CRITICAL_ERRORS|SYMOPT_NO_PROMPTS);
    if(!SymInitialize(process,nullptr,TRUE)){CloseHandle(process);return 5;}
    HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0);
    THREADENTRY32 entry={};entry.dwSize=sizeof(entry);
    for(BOOL more=Thread32First(snapshot,&entry);more;more=Thread32Next(snapshot,&entry)) {
        if(entry.th32OwnerProcessID!=pid)continue;
        HANDLE thread=OpenThread(THREAD_GET_CONTEXT|THREAD_SUSPEND_RESUME|THREAD_QUERY_LIMITED_INFORMATION,FALSE,entry.th32ThreadID);
        if(!thread)continue;
        PWSTR description=nullptr;GetThreadDescription(thread,&description);
        std::printf("thread %lu %ls\n",entry.th32ThreadID,description?description:L"");
        if(description)LocalFree(description);
        CONTEXT context={};context.ContextFlags=CONTEXT_FULL;
        bool captured=false;
        if(SuspendThread(thread)!=DWORD(-1)) {
            captured=GetThreadContext(thread,&context)!=FALSE;
            ResumeThread(thread);
        }
        if(captured) {
            STACKFRAME64 frame={};frame.AddrPC.Offset=context.Rip;frame.AddrStack.Offset=context.Rsp;frame.AddrFrame.Offset=context.Rbp;
            frame.AddrPC.Mode=frame.AddrStack.Mode=frame.AddrFrame.Mode=AddrModeFlat;
            for(int i=0;i<32 && frame.AddrPC.Offset;++i) {
                IMAGEHLP_MODULE64 module={};module.SizeOfStruct=sizeof(module);
                SymGetModuleInfo64(process,frame.AddrPC.Offset,&module);
                alignas(SYMBOL_INFO) char buffer[sizeof(SYMBOL_INFO)+1024]={};
                auto symbol=reinterpret_cast<SYMBOL_INFO*>(buffer);symbol->SizeOfStruct=sizeof(SYMBOL_INFO);symbol->MaxNameLen=1023;
                DWORD64 displacement=0;
                bool named=SymFromAddr(process,frame.AddrPC.Offset,&displacement,symbol)!=FALSE;
                std::printf("  %016llx %s+%llx %s+%llx\n",frame.AddrPC.Offset,module.ModuleName,
                    frame.AddrPC.Offset-module.BaseOfImage,named?symbol->Name:"?",named?displacement:0);
                if(!StackWalk64(IMAGE_FILE_MACHINE_AMD64,process,thread,&frame,&context,nullptr,SymFunctionTableAccess64,SymGetModuleBase64,nullptr))break;
            }
        }
        CloseHandle(thread);
    }
    CloseHandle(snapshot);SymCleanup(process);CloseHandle(process);return 0;
}
