package compile

import "fmt"

// Compile-time error: Duplicate declaration
func DuplicateDeclaration() {
	var x int = 10
	var y int = 20
	fmt.Println("x:", x, "y:", y)
	// Uncomment untuk error:
	// var x int // redeclaration of x in the same scope
	// x = 5
	// fmt.Println(x)
}
