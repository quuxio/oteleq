package main
import("bufio";"encoding/json";"os";"strconv")
var total int
func init(){if p:=os.Getenv("OTELEQ_GO_BUILD_SENTINEL");p!=""{os.WriteFile(p,[]byte("unexpected build startup"),0600)}}
func Add(value int)int{total+=value;return total+1}
func main(){scanner:=bufio.NewScanner(os.Stdin);for scanner.Scan(){if scanner.Text()=="quit"{return};n,err:=strconv.Atoi(scanner.Text());if err!=nil{panic(err)};v:=Add(n);json.NewEncoder(os.Stdout).Encode(map[string]int{"value":v,"total":total})}}
