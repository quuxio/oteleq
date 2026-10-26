package main
import "fmt"
var Calls int
func len(text string) int { Calls++; count:=0; for range []byte(text) {count++}; return count }
func main() { __oteleqAwaitGoHost(); fmt.Println(Calls) }
