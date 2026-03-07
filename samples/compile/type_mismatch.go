package compile

import "fmt"

// Compile-time error: Type mismatch
func TypeMismatch() {
	var angka int = 42
	fmt.Println("Angka:", angka)
	// Uncomment untuk error:
	// var x int = "string" // assigning string to int
	// fmt.Println(x)
}
