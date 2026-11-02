// Deliberately tiny test process, never linked into or loaded by Morrowind.
#include <windows.h>
#include <cwchar>
int wmain(int argc,wchar_t** argv) {
    if(argc!=2)return 2;
    if(!wcscmp(argv[1],L"--crash")) {*(volatile int*)0=123;return 99;}
    if(!wcscmp(argv[1],L"--wait")) {Sleep(30000);return 0;}
    if(!wcscmp(argv[1],L"--handled")) {
        __try {RaiseException(0xe0424242,0,0,nullptr);}
        __except(EXCEPTION_EXECUTE_HANDLER) {return 17;}
    }
    return 2;
}
