package staticcheck

import "fmt"

// ST1001: Incorrect package name (should be all lower-case)
func ST1001() {
	fmt.Println("Staticcheck ST1001: package name should be lower-case")
}

// ST1005: Incorrect string literal formatting
func ST1005() {
	fmt.Println("This is an error message.") // should not end with a period
}

// ST1006: Incorrect receiver naming
// Example: receiver name should match the type name or be a reasonable abbreviation

type Person struct{}

func (p *Person) ST1006() {
	fmt.Println("Receiver name is correct (p)")
}

// Incorrect receiver naming example (should be flagged by staticcheck)
// func (x *Person) ST1006Wrong() {
//     fmt.Println("Receiver name 'x' is not a reasonable abbreviation for 'Person'")
// }
