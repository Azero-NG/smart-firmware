package main

import (
	"bufio"
	"crypto/sha256"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	metadataSize = 0x24
	sectorSize   = 0x1000
)

type paceSettings struct {
	chunkSize     int
	metadataPause time.Duration
	sectorPause   time.Duration
	chunkDelay    time.Duration
}

func writePacedResponse(w io.Writer, payload []byte, settings paceSettings, sleep func(time.Duration)) (int, error) {
	header := fmt.Sprintf("HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: %d\r\nConnection: close\r\n\r\n", len(payload))
	if _, err := io.WriteString(w, header); err != nil {
		return 0, err
	}
	metadataEnd := metadataSize
	if len(payload) < metadataEnd {
		metadataEnd = len(payload)
	}
	firstEnd := metadataEnd
	if firstEnd < len(payload) {
		firstEnd += settings.chunkSize
		if firstEnd > len(payload) {
			firstEnd = len(payload)
		}
	}
	if _, err := w.Write(payload[:firstEnd]); err != nil {
		return 0, err
	}
	written := firstEnd
	if written < len(payload) {
		sleep(settings.metadataPause)
		sleep(settings.sectorPause)
	}
	for sectorStart := metadataEnd; sectorStart < len(payload); sectorStart += sectorSize {
		sectorEnd := sectorStart + sectorSize
		if sectorEnd > len(payload) {
			sectorEnd = len(payload)
		}
		first := true
		offset := sectorStart
		if sectorStart == metadataEnd {
			offset = firstEnd
			first = false
		}
		for offset < sectorEnd {
			end := offset + settings.chunkSize
			if end > sectorEnd {
				end = sectorEnd
			}
			n, err := w.Write(payload[offset:end])
			written += n
			if err != nil {
				return written, err
			}
			offset = end
			if first {
				sleep(settings.sectorPause)
				first = false
			} else if offset < sectorEnd {
				sleep(settings.chunkDelay)
			}
		}
	}
	return written, nil
}

func handleConnection(conn net.Conn, root string, settings paceSettings, logger *log.Logger) {
	defer conn.Close()
	if tcp, ok := conn.(*net.TCPConn); ok {
		_ = tcp.SetNoDelay(true)
	}
	_ = conn.SetDeadline(time.Now().Add(120 * time.Second))
	reader := bufio.NewReader(conn)
	requestLine, err := reader.ReadString('\n')
	if err != nil {
		logger.Printf("remote=%s result=request_error error=%q", conn.RemoteAddr(), err)
		return
	}
	for {
		line, readErr := reader.ReadString('\n')
		if readErr != nil {
			logger.Printf("remote=%s result=header_error error=%q", conn.RemoteAddr(), readErr)
			return
		}
		if line == "\r\n" || line == "\n" {
			break
		}
	}
	fields := strings.Fields(requestLine)
	if len(fields) != 3 || fields[0] != "GET" {
		_, _ = io.WriteString(conn, "HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
		logger.Printf("remote=%s request=%q result=bad_request", conn.RemoteAddr(), strings.TrimSpace(requestLine))
		return
	}
	name := strings.TrimPrefix(fields[1], "/")
	if name != "ct30w-recovery.bin" && name != "ct30w-stock-rollback.bin" {
		_, _ = io.WriteString(conn, "HTTP/1.1 404 Not Found\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
		logger.Printf("remote=%s path=%q result=not_found", conn.RemoteAddr(), fields[1])
		return
	}
	payload, err := os.ReadFile(filepath.Join(root, name))
	if err != nil {
		_, _ = io.WriteString(conn, "HTTP/1.1 500 Internal Server Error\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
		logger.Printf("remote=%s path=%q result=read_error error=%q", conn.RemoteAddr(), fields[1], err)
		return
	}
	started := time.Now()
	written, err := writePacedResponse(conn, payload, settings, time.Sleep)
	result := "complete"
	if err != nil {
		result = "write_error"
	}
	logger.Printf(
		"remote=%s path=%q result=%s payload_bytes=%d written=%d sha256=%x duration=%s error=%v",
		conn.RemoteAddr(), fields[1], result, len(payload), written, sha256.Sum256(payload), time.Since(started).Round(time.Millisecond), err,
	)
}

func main() {
	listen := flag.String("listen", ":18081", "listen address")
	root := flag.String("root", ".", "artifact directory")
	logPath := flag.String("log", "./ct30w-paced-server.log", "log file")
	metadataPause := flag.Duration("metadata-pause", 250*time.Millisecond, "pause after the metadata plus first body chunk")
	sectorPause := flag.Duration("sector-pause", 250*time.Millisecond, "pause after the first chunk of each 4 KiB body sector")
	chunkDelay := flag.Duration("chunk-delay", 5*time.Millisecond, "delay between remaining chunks")
	chunkSize := flag.Int("chunk-size", 512, "body chunk size")
	flag.Parse()
	if *chunkSize <= 0 || *chunkSize > sectorSize {
		log.Fatal("chunk-size must be between 1 and 4096")
	}
	logFile, err := os.OpenFile(*logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		log.Fatal(err)
	}
	defer logFile.Close()
	logger := log.New(logFile, "", log.LstdFlags|log.Lmicroseconds|log.LUTC)
	listener, err := net.Listen("tcp", *listen)
	if err != nil {
		logger.Fatal(err)
	}
	defer listener.Close()
	settings := paceSettings{chunkSize: *chunkSize, metadataPause: *metadataPause, sectorPause: *sectorPause, chunkDelay: *chunkDelay}
	logger.Printf("event=listen address=%s root=%s chunk_size=%d metadata_pause=%s sector_pause=%s chunk_delay=%s", *listen, *root, *chunkSize, *metadataPause, *sectorPause, *chunkDelay)
	for {
		conn, acceptErr := listener.Accept()
		if acceptErr != nil {
			logger.Printf("event=accept_error error=%q", acceptErr)
			continue
		}
		go handleConnection(conn, *root, settings, logger)
	}
}
