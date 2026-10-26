package main
import("fmt";"os")
func init(){if p:=os.Getenv("OTELEQ_GO_BUILD_SENTINEL");p!=""{os.WriteFile(p,[]byte("unexpected application startup"),0600)}}
func Add(value int)int{return value+1}
func main(){fmt.Print(Add(21))}
