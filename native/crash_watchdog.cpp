// Optional x86 diagnostic launcher. No injection, memory writes or exception
// repair: pass exceptions to the original handlers, dump only a last chance.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <dbghelp.h>
#include <tlhelp32.h>
#include <bcrypt.h>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <vector>
#include <iomanip>
namespace fs=std::filesystem;

static std::string hex(ULONG_PTR value) {
    std::ostringstream s;s<<"0x"<<std::hex<<value;return s.str();
}
static bool supported(const fs::path& file) {
    BCRYPT_ALG_HANDLE algorithm=nullptr;BCRYPT_HASH_HANDLE hash=nullptr;
    DWORD length=0,got=0;bool ok=false;
    if(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0)<0) return false;
    if(BCryptGetProperty(algorithm,BCRYPT_OBJECT_LENGTH,(PUCHAR)&length,sizeof(length),&got,0)>=0) {
        std::vector<UCHAR> object(length),buffer(65536);UCHAR digest[32];
        if(BCryptCreateHash(algorithm,&hash,object.data(),length,nullptr,0,0)>=0) {
            std::ifstream input(file,std::ios::binary);ok=input.is_open();
            while(input) {
                input.read((char*)buffer.data(),buffer.size());
                if(input.gcount() && BCryptHashData(hash,buffer.data(),(ULONG)input.gcount(),0)<0) {ok=false;break;}
            }
            if(ok && BCryptFinishHash(hash,digest,sizeof(digest),0)>=0) {
                std::ostringstream s;for(auto byte:digest)s<<std::hex<<std::setw(2)<<std::setfill('0')<<(int)byte;
                ok=s.str()=="eac72e1b3524ee0012d080d3c2e2e00e401464e41ee54f9afd6aaaadf2c221f5";
            } else ok=false;
            BCryptDestroyHash(hash);
        }
    }
    BCryptCloseAlgorithmProvider(algorithm,0);return ok;
}
static std::string module_at(DWORD pid,ULONG_PTR address) {
    HANDLE list=CreateToolhelp32Snapshot(TH32CS_SNAPMODULE|TH32CS_SNAPMODULE32,pid);
    if(list==INVALID_HANDLE_VALUE)return "\"fault_module\":null";
    MODULEENTRY32W item={};item.dwSize=sizeof(item);std::string result="\"fault_module\":null";
    if(Module32FirstW(list,&item))do {
        ULONG_PTR base=(ULONG_PTR)item.modBaseAddr;
        if(address>=base && address-base<item.modBaseSize) {
            // Module basenames in the supported private build are ASCII.
            std::string name;for(wchar_t c:std::wstring(item.szModule))name+=c>=32&&c<127&&c!='"'&&c!='\\'?(char)c:'?';
            result="\"fault_module\":\""+name+"\",\"module_offset\":\""+hex(address-base)+"\"";break;
        }
    }while(Module32NextW(list,&item));
    CloseHandle(list);return result;
}
int wmain(int argc,wchar_t** argv) {
    static_assert(sizeof(void*)==4,"Build this helper for the x86 game");
    wchar_t own[MAX_PATH];if(!GetModuleFileNameW(nullptr,own,MAX_PATH))return 2;
    const fs::path root=fs::path(own).parent_path().parent_path().parent_path();
#ifdef UEMW_WATCHDOG_TEST_ONLY
    const fs::path game=root/L"local/diagnostics-tests/crash-target.exe";
    const bool attach=argc==3 && !wcscmp(argv[1],L"--attach");
    std::wstring arguments=argc==2?argv[1]:L"--handled";
    if(!attach && arguments!=L"--crash" && arguments!=L"--handled" && arguments!=L"--wait")return 2;
    const fs::path pid_file=root/L"local/diagnostics-tests/child.pid";
#else
    const bool attach=argc==3 && !wcscmp(argv[1],L"--attach");
    if(!attach)return 2;
    const fs::path game=root/L"local/Morrowind/Morrowind.exe";
    if(!supported(game))return 3;
    const std::wstring arguments;
    const fs::path pid_file=root/L"local/bridge/game.pid";
#endif
    const fs::path output=root/L"local/crashes"/(std::to_wstring(GetTickCount64())+L"-"+std::to_wstring(GetCurrentProcessId()));
    fs::create_directories(output);fs::create_directories(pid_file.parent_path());
    std::ofstream events(output/L"events.jsonl");
    auto log=[&](const std::string& body){
        FILETIME ft;GetSystemTimeAsFileTime(&ft);ULARGE_INTEGER t;t.LowPart=ft.dwLowDateTime;t.HighPart=ft.dwHighDateTime;
        events<<"{\"unix_ms\":"<<(t.QuadPart/10000-11644473600000ULL)<<","<<body<<"}\n";events.flush();
    };
    STARTUPINFOW start={};start.cb=sizeof(start);start.dwFlags=STARTF_USESHOWWINDOW;start.wShowWindow=SW_SHOWNORMAL;
    PROCESS_INFORMATION process={};
    if(attach) {
        wchar_t* end=nullptr;const unsigned long requested=wcstoul(argv[2],&end,10);
        if(!requested || !end || *end)return 2;
        process.dwProcessId=requested;
        process.hProcess=OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ|SYNCHRONIZE,FALSE,requested);
        if(!process.hProcess){log("\"event\":\"open_failed\",\"win32_error\":"+std::to_string(GetLastError()));return 3;}
        wchar_t actual[MAX_PATH];DWORD size=MAX_PATH;
        fs::path expected=game;expected.make_preferred();
        if(!QueryFullProcessImageNameW(process.hProcess,0,actual,&size) || _wcsicmp(actual,expected.c_str())) {
            log("\"event\":\"refused_non_private_path\"");CloseHandle(process.hProcess);return 3;
        }
        log("\"event\":\"waiting_for_initialization\",\"pid\":"+std::to_string(requested));
#ifndef UEMW_WATCHDOG_TEST_ONLY
        bool ready=false;
        for(int attempt=0;attempt<1800;++attempt) {
            if(WaitForSingleObject(process.hProcess,100)==WAIT_OBJECT_0){CloseHandle(process.hProcess);return 0;}
            DWORD world=0,data=0;SIZE_T got=0;
            if(ReadProcessMemory(process.hProcess,(void*)0x7c67dc,&world,4,&got) && got==4 && world &&
               ReadProcessMemory(process.hProcess,(void*)0x7c67e0,&data,4,&got) && got==4 && data){ready=true;break;}
        }
        if(!ready){log("\"event\":\"initialization_timeout\"");CloseHandle(process.hProcess);return 8;}
        Sleep(1000);
#endif
        if(!DebugActiveProcess(requested)) {
            log("\"event\":\"attach_failed\",\"win32_error\":"+std::to_string(GetLastError()));CloseHandle(process.hProcess);return 4;
        }
    } else {
        std::wstring command=L"\""+game.wstring()+L"\" "+arguments;
        if(!CreateProcessW(game.c_str(),command.data(),nullptr,nullptr,FALSE,DEBUG_ONLY_THIS_PROCESS|CREATE_NEW_PROCESS_GROUP|CREATE_NO_WINDOW,
                          nullptr,game.parent_path().c_str(),&start,&process)) {
            log("\"event\":\"launch_failed\",\"win32_error\":"+std::to_string(GetLastError()));return 4;
        }
    }
    // A stopped/killed diagnostic helper must not kill the private game.
    if(!DebugSetProcessKillOnExit(FALSE)) {
        log("\"event\":\"safe_detach_failed\",\"win32_error\":"+std::to_string(GetLastError()));
        DebugActiveProcessStop(process.dwProcessId);return 5;
    }
    if(!attach)std::ofstream(pid_file)<<process.dwProcessId;
    log("\"event\":\"started\",\"pid\":"+std::to_string(process.dwProcessId)+",\"x86\":true,\"kill_on_debugger_exit\":false");
    bool first_breakpoint=true;DWORD exit_code=0;
    while(true) {
        DEBUG_EVENT event={};
        if(!WaitForDebugEvent(&event,250)) {
            if(GetLastError()==ERROR_SEM_TIMEOUT)continue;
            log("\"event\":\"wait_failed\",\"win32_error\":"+std::to_string(GetLastError()));
            DebugActiveProcessStop(process.dwProcessId);exit_code=6;break;
        }
        DWORD disposition=DBG_CONTINUE;
        if(event.dwDebugEventCode==CREATE_PROCESS_DEBUG_EVENT && event.u.CreateProcessInfo.hFile)CloseHandle(event.u.CreateProcessInfo.hFile);
        if(event.dwDebugEventCode==LOAD_DLL_DEBUG_EVENT && event.u.LoadDll.hFile)CloseHandle(event.u.LoadDll.hFile);
        if(event.dwDebugEventCode==EXCEPTION_DEBUG_EVENT) {
            auto& exception=event.u.Exception;
            disposition=DBG_EXCEPTION_NOT_HANDLED;
            if(first_breakpoint && exception.dwFirstChance && exception.ExceptionRecord.ExceptionCode==EXCEPTION_BREAKPOINT) {
                first_breakpoint=false;disposition=DBG_CONTINUE;
            } else if(!exception.dwFirstChance) {
                CONTEXT context={};context.ContextFlags=CONTEXT_FULL;
                HANDLE thread=OpenThread(THREAD_GET_CONTEXT|THREAD_QUERY_INFORMATION,FALSE,event.dwThreadId);
                const bool have_context=thread && GetThreadContext(thread,&context);
                if(thread)CloseHandle(thread);
                EXCEPTION_POINTERS pointers={&exception.ExceptionRecord,&context};
                MINIDUMP_EXCEPTION_INFORMATION info={event.dwThreadId,&pointers,FALSE};
                HANDLE file=CreateFileW((output/L"crash.dmp").c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
                bool written=false;DWORD dump_error=0;
                if(file!=INVALID_HANDLE_VALUE) {
                    written=MiniDumpWriteDump(process.hProcess,process.dwProcessId,file,
                        (MINIDUMP_TYPE)(MiniDumpWithThreadInfo|MiniDumpWithUnloadedModules|MiniDumpWithIndirectlyReferencedMemory),
                        have_context?&info:nullptr,nullptr,nullptr)!=FALSE;
                    if(!written)dump_error=GetLastError();CloseHandle(file);
                } else dump_error=GetLastError();
                log("\"event\":\"unhandled_exception\",\"code\":\""+hex(exception.ExceptionRecord.ExceptionCode)+
                    "\",\"address\":\""+hex((ULONG_PTR)exception.ExceptionRecord.ExceptionAddress)+"\",\"eip\":\""+hex(context.Eip)+
                    "\",\"thread\":"+std::to_string(event.dwThreadId)+",\"context_captured\":"+(have_context?"true":"false")+
                    ",\"dump_written\":"+(written?"true":"false")+",\"dump_error\":"+std::to_string(dump_error)+","+
                    module_at(process.dwProcessId,(ULONG_PTR)exception.ExceptionRecord.ExceptionAddress));
            }
        }
        const bool exited=event.dwDebugEventCode==EXIT_PROCESS_DEBUG_EVENT;
        if(exited) {exit_code=event.u.ExitProcess.dwExitCode;log("\"event\":\"exited\",\"exit_code\":\""+hex(exit_code)+"\"");}
        if(!ContinueDebugEvent(event.dwProcessId,event.dwThreadId,disposition)) {
            log("\"event\":\"continue_failed\",\"win32_error\":"+std::to_string(GetLastError()));
            DebugActiveProcessStop(process.dwProcessId);exit_code=7;break;
        }
        if(exited)break;
    }
    if(process.hThread)CloseHandle(process.hThread);CloseHandle(process.hProcess);return (int)exit_code;
}
