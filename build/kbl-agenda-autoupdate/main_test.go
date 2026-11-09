package main
import (
 "archive/zip"
 "bytes"
 "encoding/json"
 "os"
 "path/filepath"
 "strings"
 "testing"
)
func TestVersions(t *testing.T) {
 tests:=[]struct{a,b string; expected bool}{
  {"1.6.14","1.6.13",true},{"1.6.13","1.6.14",false},{"1.6.14","1.6.14",false},
  {"1.6.15","1.6.9",true},{"2.0.0","1.99.99",true},
 }
 for _,tt:=range tests {if newer(tt.a,tt.b)!=tt.expected{t.Fatalf("%s vs %s",tt.a,tt.b)}}
}
func mockArchive(t *testing.T,dir string,alter func(map[string][]byte)) string {
 t.Helper()
 items:=map[string][]byte{
  launcherName:bytes.Repeat([]byte{'M'},2048),
  coreName:bytes.Repeat([]byte{'C'},2048),
  "version.json":[]byte(`{"version":"1.6.15"}`),
  "LEIA_PRIMEIRO.txt":[]byte("KBL Agenda"),
 }
 if alter!=nil {alter(items)}
 name:=filepath.Join(dir,"pkg.zip")
 f,err:=os.Create(name);if err!=nil{t.Fatal(err)}
 z:=zip.NewWriter(f)
 for n,b:=range items{
  w,err:=z.Create(n);if err!=nil{t.Fatal(err)}
  if _,err=w.Write(b);err!=nil{t.Fatal(err)}
 }
 if err=z.Close();err!=nil{t.Fatal(err)}
 if err=f.Close();err!=nil{t.Fatal(err)}
 return name
}
func TestZipValidation(t *testing.T) {
 d:=t.TempDir()
 z:=mockArchive(t,d,nil)
 if _,err:=checkZip(z,"1.6.15");err!=nil{t.Fatal(err)}
 if _,err:=checkZip(z,"1.6.16");err==nil{t.Fatal("wrong version accepted")}
 z2:=mockArchive(t,d,func(m map[string][]byte){m["../bad.exe"]=[]byte("oops")})
 if _,err:=checkZip(z2,"1.6.15");err==nil{t.Fatal("path traversal accepted")}
 z3:=mockArchive(t,d,func(m map[string][]byte){delete(m,coreName)})
 if _,err:=checkZip(z3,"1.6.15");err==nil{t.Fatal("missing core accepted")}
}
func TestBackupRollbackPreservesData(t *testing.T) {
 dataRoot:=t.TempDir()
 t.Setenv("LOCALAPPDATA",dataRoot)
 dir:=filepath.Join(t.TempDir(),"installed")
 if err:=os.MkdirAll(filepath.Join(dir,"data"),0755);err!=nil{t.Fatal(err)}
 if err:=os.WriteFile(filepath.Join(dir,"data","state.json"),[]byte("PRESERVE"),0600);err!=nil{t.Fatal(err)}
 for _,f:=range orderedFiles{if err:=os.WriteFile(filepath.Join(dir,f),[]byte("BEFORE:"+f),0644);err!=nil{t.Fatal(err)}}
 bak,present,err:=backupFiles(dir);if err!=nil{t.Fatal(err)}
 for _,f:=range orderedFiles{if err:=os.WriteFile(filepath.Join(dir,f),[]byte("AFTER"),0644);err!=nil{t.Fatal(err)}}
 if err:=restoreFiles(dir,bak,present);err!=nil{t.Fatal(err)}
 for _,f:=range orderedFiles{
  b,err:=os.ReadFile(filepath.Join(dir,f))
  if err!=nil || string(b)!="BEFORE:"+f{t.Errorf("not restored: %s",f)}
 }
 b,err:=os.ReadFile(filepath.Join(dir,"data","state.json"))
 if err!=nil || strings.TrimSpace(string(b))!="PRESERVE"{t.Fatal("user data changed")}
 _=json.Valid(b)
}
