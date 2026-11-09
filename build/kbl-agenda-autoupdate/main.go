// KBL Agenda Bootstrap / Auto Updater - Windows x64, Go standard library only.
// The original Wails application is shipped unchanged as "KBL Agenda Core.exe".
// User data in %LOCALAPPDATA%\KBL Agenda is never modified by this program.
package main

import (
 "archive/zip"
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "errors"
 "flag"
 "fmt"
 "io"
 "net/http"
 "os"
 "os/exec"
 "path/filepath"
 "strconv"
 "strings"
 "syscall"
 "time"
 "unsafe"
)

const (
 manifestURL = "https://raw.githubusercontent.com/joaovictorasousa2019/KBL-Updates/main/apps/kbl-agenda/version.json"
 initialVersion = "1.6.14"
 launcherName = "KBL Agenda.exe"
 coreName = "KBL Agenda Core.exe"
 maxPackage = 120 << 20
 maxExpanded = 180 << 20
)
var orderedFiles = []string{coreName, "LEIA_PRIMEIRO.txt", launcherName, "version.json"}
var allowedFiles = map[string]bool{coreName:true,"LEIA_PRIMEIRO.txt":true,launcherName:true,"version.json":true}

type release struct {
 Version string `json:"version"`
 Published bool `json:"published"`
 DownloadURL string `json:"download_url"`
 SHA256 string `json:"sha256"`
}
type localVersion struct { Version string `json:"version"` }

func logLine(s string) {
 root:=os.Getenv("LOCALAPPDATA")
 if root=="" {root=os.TempDir()}
 dir:=filepath.Join(root,"KBL Agenda","Updater")
 if os.MkdirAll(dir,0700)!=nil{return}
 f,err:=os.OpenFile(filepath.Join(dir,"update.log"),os.O_CREATE|os.O_APPEND|os.O_WRONLY,0600)
 if err!=nil{return}
 defer f.Close()
 fmt.Fprintln(f,time.Now().Format(time.RFC3339),s)
}
func ver(v string) [3]int {
 var a [3]int
 for i,p:=range strings.Split(strings.TrimLeft(strings.TrimSpace(v),"vV"),".") {
  if i>=3 {break}
  j:=0;for j<len(p) && p[j]>='0' && p[j]<='9' {j++}
  a[i],_=strconv.Atoi(p[:j])
 }
 return a
}
func newer(a,b string) bool {
 x,y:=ver(a),ver(b)
 for i:=0;i<3;i++ {if x[i]!=y[i]{return x[i]>y[i]}}
 return false
}
func local(dir string) string {
 b,err:=os.ReadFile(filepath.Join(dir,"version.json"))
 if err==nil {
  var v localVersion
  if json.Unmarshal(b,&v)==nil && v.Version!=""{return v.Version}
 }
 return initialVersion
}
func currentRelease() (release,error) {
 var r release
 req,err:=http.NewRequest("GET",manifestURL+"?ts="+strconv.FormatInt(time.Now().UnixNano(),10),nil)
 if err!=nil{return r,err}
 req.Header.Set("Cache-Control","no-cache")
 client:=&http.Client{Timeout:5*time.Second}
 resp,err:=client.Do(req);if err!=nil{return r,err}
 defer resp.Body.Close()
 if resp.StatusCode!=200{return r,fmt.Errorf("manifest HTTP %d",resp.StatusCode)}
 b,err:=io.ReadAll(io.LimitReader(resp.Body,65536))
 if err!=nil{return r,err}
 if err=json.Unmarshal(b,&r);err!=nil{return r,err}
 if !r.Published{return r,errors.New("release unpublished")}
 if len(r.SHA256)!=64{return r,errors.New("invalid manifest hash")}
 if _,err:=hex.DecodeString(r.SHA256);err!=nil{return r,err}
 if !strings.HasPrefix(r.DownloadURL,"https://raw.githubusercontent.com/joaovictorasousa2019/KBL-Updates/"){return r,errors.New("untrusted download URL")}
 return r,nil
}
func fetchPackage(r release) (string,error) {
 req,err:=http.NewRequest("GET",r.DownloadURL,nil);if err!=nil{return "",err}
 client:=&http.Client{Timeout:120*time.Second}
 resp,err:=client.Do(req);if err!=nil{return "",err}
 defer resp.Body.Close()
 if resp.StatusCode!=200{return "",fmt.Errorf("package HTTP %d",resp.StatusCode)}
 dir,err:=os.MkdirTemp("","kbl-agenda-package-*");if err!=nil{return "",err}
 name:=filepath.Join(dir,"update.zip")
 f,err:=os.Create(name);if err!=nil {os.RemoveAll(dir);return "",err}
 h:=sha256.New()
 n,err:=io.Copy(io.MultiWriter(f,h),io.LimitReader(resp.Body,maxPackage+1))
 closeErr:=f.Close()
 if err!=nil || closeErr!=nil || n>maxPackage || !strings.EqualFold(hex.EncodeToString(h.Sum(nil)),r.SHA256){
  os.RemoveAll(dir)
  return "",fmt.Errorf("package download/hash verification failed: size=%d err=%v",n,err)
 }
 return name,nil
}
func copyFile(src,dst string) error {
 in,err:=os.Open(src);if err!=nil{return err};defer in.Close()
 if err=os.MkdirAll(filepath.Dir(dst),0755);err!=nil{return err}
 out,err:=os.OpenFile(dst,os.O_CREATE|os.O_WRONLY|os.O_TRUNC,0755);if err!=nil{return err}
 _,err=io.Copy(out,in)
 c:=out.Close();if err!=nil{return err};return c
}
func launchCore(dir string) error {
 p:=filepath.Join(dir,coreName)
 if _,err:=os.Stat(p);err!=nil{return fmt.Errorf("app core missing: %w",err)}
 cmd:=exec.Command(p);cmd.Dir=dir
 return cmd.Run()
}
func uniqueInstance() (func(),bool) {
 name,err:=syscall.UTF16PtrFromString("Local\\KBL_Agenda_Launcher")
 if err!=nil{return func(){},true}
 kernel:=syscall.NewLazyDLL("kernel32.dll").NewProc("CreateMutexW")
 h,_,callErr:=kernel.Call(0,0,uintptr(unsafe.Pointer(name)))
 if h==0 {logLine("mutex error: "+fmt.Sprint(callErr));return func(){},true}
 if callErr==syscall.Errno(183) {syscall.CloseHandle(syscall.Handle(h));return func(){},false}
 return func(){syscall.CloseHandle(syscall.Handle(h))},true
}
func startHelper(exe,dir,pkg string,r release) error {
 tmp,err:=os.MkdirTemp("","kbl-agenda-helper-*");if err!=nil{return err}
 helper:=filepath.Join(tmp,"KBL Agenda Installer.exe")
 if err=copyFile(exe,helper);err!=nil{return err}
 cmd:=exec.Command(helper,"--apply","--dir",dir,"--zip",pkg,"--sha",r.SHA256,"--version",r.Version,"--pid",strconv.Itoa(os.Getpid()))
 cmd.Dir=tmp
 if err=cmd.Start();err!=nil{return err}
 return cmd.Process.Release()
}
func waitForPID(pid int) error {
 if pid<=0{return errors.New("parent PID missing")}
 h,err:=syscall.OpenProcess(0x00100000,false,uint32(pid))
 if err!=nil{return nil} // Parent already exited.
 defer syscall.CloseHandle(h)
 status,err:=syscall.WaitForSingleObject(h,45000)
 if err!=nil{return err}
 if status!=0{return errors.New("old application did not exit in 45 seconds")}
 return nil
}
func isAlive(pid int) bool {
 h,err:=syscall.OpenProcess(0x00100000,false,uint32(pid))
 if err!=nil{return false}
 defer syscall.CloseHandle(h)
 status,err:=syscall.WaitForSingleObject(h,0)
 return err==nil && status==258
}
func checkZip(path string,expectedVersion string) (map[string][]byte,error) {
 zr,err:=zip.OpenReader(path);if err!=nil{return nil,err};defer zr.Close()
 contents:=map[string][]byte{}
 var total uint64
 for _,f:=range zr.File{
  if !allowedFiles[f.Name] || f.FileInfo().IsDir() || f.Mode()&os.ModeSymlink!=0 || f.UncompressedSize64>maxExpanded {
   return nil,fmt.Errorf("unapproved archive entry: %s",f.Name)
  }
  if _,exists:=contents[f.Name];exists{return nil,fmt.Errorf("duplicate archive entry: %s",f.Name)}
  total+=f.UncompressedSize64
  if total>maxExpanded{return nil,errors.New("archive exceeds size limit")}
  rc,err:=f.Open();if err!=nil{return nil,err}
  b,readErr:=io.ReadAll(io.LimitReader(rc,int64(f.UncompressedSize64)+1));closeErr:=rc.Close()
  if readErr!=nil || closeErr!=nil || uint64(len(b))!=f.UncompressedSize64{return nil,fmt.Errorf("corrupt archive member: %s",f.Name)}
  contents[f.Name]=b
 }
 for _,name:=range orderedFiles{if _,ok:=contents[name];!ok{return nil,fmt.Errorf("missing archive member: %s",name)}}
 var v localVersion
 if err:=json.Unmarshal(contents["version.json"],&v);err!=nil{return nil,err}
 if v.Version!=expectedVersion{return nil,errors.New("archive version mismatch")}
 if len(contents[coreName])<1024 || len(contents[launcherName])<1024 {return nil,errors.New("executable too small")}
 return contents,nil
}
func backupFiles(dir string) (string,map[string]bool,error) {
 base:=os.Getenv("LOCALAPPDATA");if base==""{base=os.TempDir()}
 backup:=filepath.Join(base,"KBL Agenda","Updater","backups",time.Now().UTC().Format("20060102T150405.000000000"))
 if err:=os.MkdirAll(backup,0700);err!=nil{return "",nil,err}
 present:=map[string]bool{}
 for _,name:=range orderedFiles{
  src:=filepath.Join(dir,name)
  if _,err:=os.Stat(src);err==nil{
   present[name]=true
   if err=copyFile(src,filepath.Join(backup,name));err!=nil{return "",nil,err}
  }else if !os.IsNotExist(err){return "",nil,err}
 }
 return backup,present,nil
}
func restoreFiles(dir,backup string,present map[string]bool) error {
 var first error
 for _,name:=range orderedFiles{
  dst:=filepath.Join(dir,name)
  if present[name] {
   if err:=copyFile(filepath.Join(backup,name),dst);err!=nil && first==nil{first=err}
  } else if err:=os.Remove(dst);err!=nil && !os.IsNotExist(err) && first==nil{first=err}
 }
 return first
}
func writeFileSafely(dir,name string,data []byte) error {
 dest:=filepath.Join(dir,name)
 tmp:=dest+".kblnew"
 if err:=os.WriteFile(tmp,data,0755);err!=nil{return err}
 if err:=os.Rename(tmp,dest);err==nil{return nil}
 if err:=os.Remove(dest);err!=nil && !os.IsNotExist(err){os.Remove(tmp);return err}
 err:=os.Rename(tmp,dest)
 if err!=nil{os.Remove(tmp)}
 return err
}
func launchAndCheck(dir string) error {
 cmd:=exec.Command(filepath.Join(dir,launcherName))
 cmd.Dir=dir
 if err:=cmd.Start();err!=nil{return err}
 pid:=cmd.Process.Pid
 _=cmd.Process.Release()
 time.Sleep(4*time.Second)
 if !isAlive(pid){return errors.New("new launcher exited during startup smoke test")}
 return nil
}
func apply(dir,pkg,hash,version string,pid int) error {
 if !filepath.IsAbs(dir) {return errors.New("absolute install directory required")}
 if len(hash)!=64 {return errors.New("invalid expected sha")}
 b,err:=os.ReadFile(pkg);if err!=nil{return err}
 sum:=sha256.Sum256(b)
 if !strings.EqualFold(hex.EncodeToString(sum[:]),hash){return errors.New("SHA-256 check failed")}
 contents,err:=checkZip(pkg,version);if err!=nil{return err}
 if err=waitForPID(pid);err!=nil{return err}
 backup,present,err:=backupFiles(dir);if err!=nil{return err}
 logLine("backup created: "+backup)
 for _,name:=range orderedFiles {
  if err=writeFileSafely(dir,name,contents[name]);err!=nil{
   restoreErr:=restoreFiles(dir,backup,present)
   return fmt.Errorf("install failed at %s: %v; rollback: %v",name,err,restoreErr)
  }
 }
 if err=launchAndCheck(dir);err!=nil {
  restoreErr:=restoreFiles(dir,backup,present)
  if restoreErr==nil {
   old:=exec.Command(filepath.Join(dir,launcherName));old.Dir=dir
   if startErr:=old.Start();startErr==nil{old.Process.Release()}
  }
  return fmt.Errorf("new launch failed: %v; rollback: %v",err,restoreErr)
 }
 logLine("update completed successfully to "+version)
 return nil
}
func main(){
 if len(os.Args)>1 && os.Args[1]=="--apply" {
  fs:=flag.NewFlagSet("apply",flag.ContinueOnError)
  dir:=fs.String("dir","","");pkg:=fs.String("zip","","")
  hash:=fs.String("sha","","");version:=fs.String("version","","");pid:=fs.Int("pid",0,"")
  if err:=fs.Parse(os.Args[2:]);err!=nil{logLine("invalid update flags: "+err.Error());return}
  err:=apply(*dir,*pkg,*hash,*version,*pid)
  if err!=nil{logLine("UPDATE FAILED: "+err.Error())}
  _=os.Remove(*pkg)
  return
 }
 exe,err:=os.Executable();if err!=nil{logLine("executable: "+err.Error());return}
 dir:=filepath.Dir(exe)
 unlock,ok:=uniqueInstance();if !ok{return};defer unlock()
 if os.Getenv("KBL_AGENDA_SKIP_UPDATE")!="1"{
  r,err:=currentRelease()
  if err!=nil{logLine("check skipped: "+err.Error())}else if newer(r.Version,local(dir)){
   pkg,err:=fetchPackage(r)
   if err!=nil{logLine("download skipped: "+err.Error())}else{
    if err=startHelper(exe,dir,pkg,r);err==nil{return}
    logLine("helper launch failed: "+err.Error())
    _=os.RemoveAll(filepath.Dir(pkg))
   }
  }
 }
 if err:=launchCore(dir);err!=nil {logLine("agenda exited: "+err.Error())}
}
