package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

type applyResult struct {
	Success bool   `json:"success"`
	Error   string `json:"error,omitempty"`
}

func doApply(source, target, filesType string) ([]byte, error) {
	manifestPath := filepath.Join(source, "manifest.json")
	manifest, err := readManifest(manifestPath)
	if err != nil {
		return marshalApplyResult(false, fmt.Sprintf("cannot read manifest: %v", err))
	}

	var hadErrors bool
	var lastError string
	for _, f := range manifest.Files {
		if f.Reload != filesType {
			continue
		}

		dst := filepath.Join(target, f.Path)
		src := filepath.Join(source, f.Path)

		err := applyFile(src, dst, f.SHA256)
		if err != nil {
			hadErrors = true
			lastError = err.Error()
		}
	}

	if hadErrors {
		return marshalApplyResult(false, lastError)
	}
	return marshalApplyResult(true, "")
}

func applyFile(src, dst, expectedSHA string) error {
	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return fmt.Errorf("mkdir: %w", err)
	}

	tmp := dst + ".tmp"
	if err := copyFile(src, tmp); err != nil {
		return fmt.Errorf("copy: %w", err)
	}

	if expectedSHA != "" {
		actual, err := computeSHA256(tmp)
		if err != nil {
			os.Remove(tmp)
			return fmt.Errorf("sha256: %w", err)
		}
		if actual != expectedSHA {
			os.Remove(tmp)
			return fmt.Errorf("sha256 mismatch: expected %s, got %s", expectedSHA, actual)
		}
	}

	if err := os.Rename(tmp, dst); err != nil {
		os.Remove(tmp)
		return fmt.Errorf("rename: %w", err)
	}
	return nil
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()

	_, err = io.Copy(out, in)
	return err
}

func marshalApplyResult(success bool, errMsg string) ([]byte, error) {
	r := applyResult{Success: success}
	if errMsg != "" {
		r.Error = errMsg
	}
	return json.Marshal(r)
}
