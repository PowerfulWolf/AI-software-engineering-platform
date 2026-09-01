package main

import "testing"

func TestGreeting(t *testing.T) {
	if greeting("world") != "hello, world" {
		t.Fatal("unexpected greeting")
	}
}
