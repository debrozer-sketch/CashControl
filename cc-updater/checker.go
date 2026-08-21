package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

type fileEntry struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`
	Reload string `json:"reload"`
}

type manifestData struct {
	Version     string      `json:"version"`
	Description string      `json:"description"`
	Files       []fileEntry `json:"files"`
}

type checkResult struct {
	Available    bool     `json:"available"`
	Version      string   `json:"version"`
	Updated      []string `json:"updated"`
	Removed      []string `json:"removed"`
	HotFiles     []string `json:"hot_files"`
	ColdFiles    []string `json:"cold_files"`
	ColdRequired bool     `json:"cold_required"`
	Error        string   `json:"error,omitempty"`
}

func doCheck(source, target string) ([]byte, error) {
	manifestPath := filepath.Join(source, "manifest.json")
	manifest, err := readManifest(manifestPath)
	if err != nil {
		msg := fmt.Sprintf("cannot read manifest: %v", err)
		return marshalResult("", false, nil, nil, msg)
	}

	var hot, cold []string
	for _, f := range manifest.Files {
		localPath := filepath.Join(target, f.Path)
		localSHA, _ := computeSHA256(localPath)
		if localSHA != f.SHA256 {
			switch f.Reload {
			case "hot":
				hot = append(hot, f.Path)
			default:
				cold = append(cold, f.Path)
			}
		}
	}

	available := len(hot)+len(cold) > 0
	return marshalResult(manifest.Version, available, hot, cold, "")
}

func readVersion(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return string(data)
}

func readManifest(path string) (*manifestData, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var m manifestData
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, err
	}
	return &m, nil
}

func marshalResult(version string, available bool, hot, cold []string, errMsg string) ([]byte, error) {
	if hot == nil {
		hot = []string{}
	}
	if cold == nil {
		cold = []string{}
	}
	updated := make([]string, 0, len(hot)+len(cold))
	updated = append(updated, hot...)
	updated = append(updated, cold...)

	return json.Marshal(checkResult{
		Available:    available,
		Version:      version,
		Updated:      updated,
		Removed:      []string{},
		HotFiles:     hot,
		ColdFiles:    cold,
		ColdRequired: len(cold) > 0,
		Error:        errMsg,
	})
}