package main
import "fmt"
type int struct{}
func (int) GoString() string {fmt.Println("CALLBACK");return "masked"}
func selected() int{return int{}}
