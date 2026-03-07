package compile

import "fmt"

// Compile-time error: Constant overflow
func ConstantOverflow() {
	var y int8 = 127
	fmt.Println("Nilai maksimum int8:", y)
	// Uncomment untuk error:
	// var x int8 = 300 // 300 exceeds int8 range (-128 to 127)
	// fmt.Println(x)
}
