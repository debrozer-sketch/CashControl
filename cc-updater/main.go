package main

import (
	"flag"
	"fmt"
	"os"
)

func main() {
	checkCmd := flag.NewFlagSet("--check", flag.ExitOnError)
	source := checkCmd.String("source", "", "Network source path (UNC or local)")
	target := checkCmd.String("target", "", "Target application directory")

	applyCmd := flag.NewFlagSet("--apply", flag.ExitOnError)
	applySource := applyCmd.String("source", "", "Network source path")
	applyTarget := applyCmd.String("target", "", "Target application directory")
	applyFiles := applyCmd.String("files", "", "File type: hot or cold")

	if len(os.Args) < 2 {
		printUsage()
		os.Exit(1)
	}

	switch os.Args[1] {
	case "--check":
		checkCmd.Parse(os.Args[2:])
		if *source == "" || *target == "" {
			fmt.Fprintln(os.Stderr, "--check requires --source and --target")
			os.Exit(1)
		}
		result, err := doCheck(*source, *target)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		fmt.Print(string(result))

	case "--apply":
		applyCmd.Parse(os.Args[2:])
		if *applySource == "" || *applyTarget == "" || *applyFiles == "" {
			fmt.Fprintln(os.Stderr, "--apply requires --source, --target and --files")
			os.Exit(1)
		}
		if *applyFiles != "hot" && *applyFiles != "cold" {
			fmt.Fprintln(os.Stderr, "--files must be 'hot' or 'cold'")
			os.Exit(1)
		}
		result, err := doApply(*applySource, *applyTarget, *applyFiles)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		fmt.Print(string(result))

	case "--version":
		fmt.Println("cc-updater 3.0.0")

	default:
		printUsage()
		os.Exit(1)
	}
}

func printUsage() {
	fmt.Fprintf(os.Stderr, `cc-updater — update utility for CashControl

Usage:
  cc-updater --check --source <path> --target <path>
  cc-updater --apply --source <path> --target <path> --files <hot|cold>
  cc-updater --version
`)
}