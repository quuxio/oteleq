package main
import (__oteleq_fmt "fmt"; __oteleq_os "os"; __oteleq_math "math")

import "fmt"
type int struct{}
func (int) GoString() string {fmt.Println("CALLBACK");return "masked"}
func selected() int{return int{}}

func __oteleqValue(v any) string {
 switch x:=v.(type) {case float32: return __oteleq_fmt.Sprintf("float32:%x",__oteleq_math.Float32bits(x));case float64:return __oteleq_fmt.Sprintf("float64:%x",__oteleq_math.Float64bits(x))}
 switch v.(type) {case nil,bool,string,int,int8,int16,int32,int64,uint,uint8,uint16,uint32,uint64:default:panic("opaque observation requires a fixture")}
 return __oteleq_fmt.Sprintf("%T:%#v",v,v)
}
func main(){
 s:="before\n"; 
 func(){defer func(){if p:=recover();p!=nil{s+="error:"+__oteleqValue(p)+"\n"}}();s+="return:"+__oteleqValue(selected())+"\n"}()
 s+="after\n"; 
 if err:=__oteleq_os.WriteFile(__oteleq_os.Getenv("OTELEQ_OBSERVATION"),[]byte(s),0600);err!=nil{panic(err)}
}
