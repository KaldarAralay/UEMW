#include <windows.h>
#include <tlhelp32.h>
#include <bcrypt.h>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <iomanip>
#include <vector>
#include <string>
namespace fs=std::filesystem;

static bool Supported(const fs::path& file) {
    BCRYPT_ALG_HANDLE algorithm=nullptr;BCRYPT_HASH_HANDLE hash=nullptr;
    DWORD length=0,got=0;bool ok=false;
    if(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0)<0)return false;
    if(BCryptGetProperty(algorithm,BCRYPT_OBJECT_LENGTH,(PUCHAR)&length,sizeof(length),&got,0)>=0){
        std::vector<UCHAR> object(length),buffer(65536);UCHAR digest[32];
        if(BCryptCreateHash(algorithm,&hash,object.data(),length,nullptr,0,0)>=0){
            std::ifstream input(file,std::ios::binary);ok=input.is_open();
            while(input){input.read((char*)buffer.data(),buffer.size());if(input.gcount()&&BCryptHashData(hash,buffer.data(),(ULONG)input.gcount(),0)<0){ok=false;break;}}
            if(ok&&BCryptFinishHash(hash,digest,sizeof(digest),0)>=0){
                std::ostringstream text;for(auto byte:digest)text<<std::hex<<std::setw(2)<<std::setfill('0')<<(int)byte;
                ok=text.str()=="eac72e1b3524ee0012d080d3c2e2e00e401464e41ee54f9afd6aaaadf2c221f5";
            }else ok=false;
        }
    }
    if(hash)BCryptDestroyHash(hash);BCryptCloseAlgorithmProvider(algorithm,0);return ok;
}
static std::string Quote(const std::wstring& value){
    const int count=WideCharToMultiByte(CP_UTF8,0,value.data(),(int)value.size(),nullptr,0,nullptr,nullptr);
    std::string utf8(count,'\0');WideCharToMultiByte(CP_UTF8,0,value.data(),(int)value.size(),utf8.data(),count,nullptr,nullptr);
    std::string out="\"";for(char c:utf8){if(c=='\\'||c=='\"')out+='\\';out+=c;}return out+'\"';
}
static bool OtherGame(){
    const HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0);if(snapshot==INVALID_HANDLE_VALUE)return true;
    PROCESSENTRY32W entry{};entry.dwSize=sizeof(entry);bool found=false;
    if(Process32FirstW(snapshot,&entry))do{if(_wcsicmp(entry.szExeFile,L"Morrowind.exe")==0){found=true;break;}}while(Process32NextW(snapshot,&entry));
    CloseHandle(snapshot);return found;
}
int WINAPI wWinMain(HINSTANCE,HINSTANCE,PWSTR args,int){
    wchar_t module[32768]{};if(!GetModuleFileNameW(nullptr,module,32768))return 10;
    const fs::path bin=fs::path(module).parent_path(),root=bin.parent_path().parent_path(),game=root/L"local"/L"Morrowind",exe=game/L"Morrowind.exe";
    const bool quiet=std::wstring(args).find(L"--quiet")!=std::wstring::npos;
    DWORD pid=0,exitCode=0,error=0;bool exited=true;std::string message;
    if(bin.filename()!=L"bin"||bin.parent_path().filename()!=L"local")message="Bootstrap must stay in this project's local/bin directory.";
    else if(!Supported(exe))message="Unsupported private executable; no game started.";
    else if(OtherGame())message="A Morrowind game is already running; it was left untouched.";
    else {
        std::ifstream appFile(game/L"steam_appid.txt");std::string app;appFile>>app;
        if(app!="22320")message="Private steam_appid.txt is missing or invalid.";
        else if(!SetCurrentDirectoryW(game.c_str())||!SetEnvironmentVariableW(L"SteamAppId",L"22320")||!SetEnvironmentVariableW(L"SteamGameId",L"22320")){error=GetLastError();message="Could not establish the private startup context.";}
        else {
            STARTUPINFOW startup{};startup.cb=sizeof(startup);PROCESS_INFORMATION process{};std::wstring command=L"\""+exe.wstring()+L"\"";
            if(!CreateProcessW(exe.c_str(),command.data(),nullptr,nullptr,FALSE,CREATE_UNICODE_ENVIRONMENT,nullptr,game.c_str(),&startup,&process)){error=GetLastError();message="Windows could not start private Morrowind.";}
            else {
                pid=process.dwProcessId;CloseHandle(process.hThread);
                const DWORD wait=WaitForSingleObject(process.hProcess,2000);exited=wait==WAIT_OBJECT_0;
                if(exited){GetExitCodeProcess(process.hProcess,&exitCode);message="Private Morrowind exited before startup completed.";}
                else if(wait!=WAIT_TIMEOUT){error=GetLastError();message="Could not verify private startup.";}
                CloseHandle(process.hProcess);
            }
        }
    }
    if(fs::exists(root/L"logs")){
        const fs::path report=root/L"logs"/L"native-bootstrap.json",temporary=report.wstring()+L".tmp";
        std::ofstream out(temporary,std::ios::binary|std::ios::trunc);
        out<<"{\"version\":3,\"api\":\"CreateProcessW\",\"bootstrap_pid\":"<<GetCurrentProcessId()<<",\"pid\":"<<pid<<",\"executable\":"<<Quote(exe.wstring())<<",\"working_directory\":"<<Quote(game.wstring())<<",\"steam_app_id\":\"22320\",\"exited\":"<<(exited?"true":"false")<<",\"exit_code\":"<<(exited?std::to_string(exitCode):"null")<<",\"windows_error\":"<<error<<",\"error\":\""<<message<<"\"}";
        out.close();MoveFileExW(temporary.c_str(),report.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH);
        if(message.empty()){std::ofstream pidFile(root/L"local"/L"bridge"/L"game.pid",std::ios::trunc);pidFile<<pid<<'\n';}
    }
    if(!message.empty()&&!quiet){std::wstring text(message.begin(),message.end());MessageBoxW(nullptr,text.c_str(),L"UEMW private startup",MB_OK|MB_ICONERROR);}
    return message.empty()?0:1;
}
