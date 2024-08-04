package main

/*
#include <stdlib.h>
*/
import "C"
import "github.com/apernet/hysteria/app/v2/cmd"

//export startClientFromJSON
func startClientFromJSON(json string) {
	cmd.StartFromJSON(json)
}

func main() {
	cmd.Execute()
}
