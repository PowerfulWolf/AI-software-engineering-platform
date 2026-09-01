package main

import "fmt"

func greeting(name string) string {
	return fmt.Sprintf("hello, %s", name)
}

func main() {
	fmt.Println(greeting("world"))
}
