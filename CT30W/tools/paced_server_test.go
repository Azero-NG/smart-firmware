package main

import (
	"bytes"
	"io"
	"log"
	"net"
	"os"
	"strings"
	"testing"
	"time"
)

type writeRecorder struct{ parts [][]byte }

func (w *writeRecorder) Write(p []byte) (int, error) {
	w.parts = append(w.parts, append([]byte(nil), p...))
	return len(p), nil
}

func TestWritePacedResponseCoalescesMetadataWithFirstBodyChunk(t *testing.T) {
	payload := bytes.Repeat([]byte{0x5a}, metadataSize+sectorSize+700)
	recorder := &writeRecorder{}
	var sleeps []time.Duration
	settings := paceSettings{chunkSize: 512, metadataPause: 300 * time.Millisecond, sectorPause: 250 * time.Millisecond, chunkDelay: 5 * time.Millisecond}
	written, err := writePacedResponse(recorder, payload, settings, func(d time.Duration) { sleeps = append(sleeps, d) })
	if err != nil || written != len(payload) {
		t.Fatalf("written=%d err=%v", written, err)
	}
	if len(recorder.parts[1]) != metadataSize+settings.chunkSize {
		t.Fatalf("first payload write=%d", len(recorder.parts[1]))
	}
	var reconstructed bytes.Buffer
	for _, part := range recorder.parts[1:] { reconstructed.Write(part) }
	if !bytes.Equal(reconstructed.Bytes(), payload) { t.Fatal("payload changed") }
	if len(sleeps) == 0 || sleeps[0] != settings.metadataPause { t.Fatalf("sleeps=%v", sleeps) }
}

func TestWhitelistAndCompleteLog(t *testing.T) {
	root := t.TempDir()
	payload := bytes.Repeat([]byte{0x42}, 128)
	if err := os.WriteFile(root+"/ct30w-recovery.bin", payload, 0o600); err != nil { t.Fatal(err) }
	var output bytes.Buffer
	logger := log.New(&output, "", 0)
	server, client := net.Pipe()
	done := make(chan struct{})
	go func() {
		defer close(done)
		handleConnection(server, root, paceSettings{chunkSize: 512}, logger)
	}()
	_, _ = io.WriteString(client, "GET /ct30w-recovery.bin HTTP/1.1\r\nHost: test\r\n\r\n")
	response, _ := io.ReadAll(client)
	_ = client.Close()
	<-done
	if !bytes.Contains(response, payload) { t.Fatal("payload absent") }
	if !strings.Contains(output.String(), "result=complete") || strings.Contains(output.String(), "%!") {
		t.Fatalf("log=%q", output.String())
	}
}
