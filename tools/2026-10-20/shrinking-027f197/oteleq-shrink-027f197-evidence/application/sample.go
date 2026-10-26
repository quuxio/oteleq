package main
import "runtime"
func sample(value int) int {if value>=7 && runtime.NumGoroutine()>1{return 1};return 0}
