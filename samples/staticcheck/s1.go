package staticcheck

import "fmt"

// S1003: Replace with direct assignment
func S1003() {
	var x int
	x = 5
	fmt.Println(x)
}

// S1002: Use fmt.Println instead of fmt.Printf for simple output
func S1002() {
	fmt.Println("Hello, World!")
}

// S1001: Replace loop with range
func S1001() {
	arr := []int{1, 2, 3}
	for _, v := range arr {
		fmt.Println(v)
	}
}
