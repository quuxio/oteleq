package main
import (__oteleq_fmt "fmt"; __oteleq_os "os"; __oteleq_math "math"; __oteleq_reflect "reflect")

var Total int
func Add(value int)int{Total+=value;return Total+1}
func __oteleq_original_main(){}

func __oteleqValue(v interface{}) string {
 x:=__oteleq_reflect.ValueOf(v)
 if !x.IsValid(){return "<nil>:<nil>"}
 kind:=x.Type().String()+":"
 if x.Type().String()!=x.Kind().String(){kind="@"+x.Kind().String()+"|"+kind}
 switch x.Kind() {
 case __oteleq_reflect.Float32:
  bits:=__oteleq_reflect.ValueOf(__oteleq_math.Float32bits).Call([]__oteleq_reflect.Value{x.Convert(__oteleq_reflect.TypeOf(__oteleq_math.Float32frombits(0)))})[0].Uint()
  return kind+__oteleq_fmt.Sprintf("%08x",bits)
 case __oteleq_reflect.Float64:return kind+__oteleq_fmt.Sprintf("%016x",__oteleq_math.Float64bits(x.Float()))
 case __oteleq_reflect.Bool:return kind+__oteleq_fmt.Sprintf("%#v",x.Bool())
 case __oteleq_reflect.String:return kind+__oteleq_fmt.Sprintf("%#v",x.String())
 case __oteleq_reflect.Int,__oteleq_reflect.Int8,__oteleq_reflect.Int16,__oteleq_reflect.Int32,__oteleq_reflect.Int64:return kind+__oteleq_fmt.Sprintf("%#v",x.Int())
 case __oteleq_reflect.Uint,__oteleq_reflect.Uint8,__oteleq_reflect.Uint16,__oteleq_reflect.Uint32,__oteleq_reflect.Uint64:return kind+__oteleq_fmt.Sprintf("%#v",x.Uint())
 default:__oteleq_os.Exit(91);return ""
 }
}
func main(){
 __oteleqAwaitGoHost();
 s:=__oteleq_fmt.Sprintf(`abi:{"pointer_bits":%d}`+"\nbefore\n",__oteleq_reflect.TypeOf(0).Bits()); s+="Total:"+__oteleqValue(Total)+"\n"
 func(){defer func(){if p:=recover();__oteleq_reflect.ValueOf(p).IsValid(){s+="error:"+__oteleqValue(p)+"\n"}}();s+="return:"+__oteleqValue(Add(int(21)))+"\n"}()
 s+="after\n"; s+="Total:"+__oteleqValue(Total)+"\n"
 if err:=__oteleq_os.WriteFile(__oteleq_os.Getenv("OTELEQ_OBSERVATION"),[]byte(s),0600);__oteleq_reflect.ValueOf(err).IsValid(){panic(err)}
}
