package main

import (
	"bytes"
	"compress/gzip"
	"crypto/rand"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"
)

// seen is what the stand-in backend recorded about one request
type seen struct {
	method string
	path   string
	query  string
	host   string
	header http.Header
	body   []byte
}

// backend is a stand-in for the real backend: it records the requests
// that reach it and answers with what the test asks for
type backend struct {
	server *httptest.Server
	mu     sync.Mutex
	seen   []seen
}

func newBackend(t *testing.T, handler http.HandlerFunc) *backend {
	t.Helper()
	b := &backend{}
	b.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		b.mu.Lock()
		b.seen = append(b.seen, seen{r.Method, r.URL.Path, r.URL.RawQuery, r.Host, r.Header.Clone(), body})
		b.mu.Unlock()
		r.Body = io.NopCloser(bytes.NewReader(body))
		handler(w, r)
	}))
	t.Cleanup(b.server.Close)
	return b
}

// requests returns the recorded requests, leaving out the keep-alive ones
func (b *backend) requests() []seen {
	b.mu.Lock()
	defer b.mu.Unlock()
	var out []seen
	for _, s := range b.seen {
		if s.path != livenessPath {
			out = append(out, s)
		}
	}
	return out
}

func (b *backend) livenessChecks() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	n := 0
	for _, s := range b.seen {
		if s.path == livenessPath {
			n++
		}
	}
	return n
}

var testTimeouts = Timeouts{
	Connect:        2 * time.Second,
	ResponseHeader: 500 * time.Millisecond,
	IdleConnection: time.Minute,
	KeepAlive:      time.Second,
}

// newFront starts a forwarder in front of the given backend address and
// returns its address and what it logs
func newFront(t *testing.T, backendURL string) (string, *bytes.Buffer) {
	t.Helper()
	target, err := ParseTarget(backendURL)
	if err != nil {
		t.Fatalf("ParseTarget: %v", err)
	}
	var logged bytes.Buffer
	var mu sync.Mutex
	logger := log.New(lockedWriter{&mu, &logged}, "", 0)
	front := httptest.NewServer(NewForwarder(target, testTimeouts, logger))
	t.Cleanup(front.Close)
	return front.URL, &logged
}

type lockedWriter struct {
	mu *sync.Mutex
	w  io.Writer
}

func (l lockedWriter) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.w.Write(p)
}

// A client that follows no redirects and asks for no compression by
// itself, like the forwarder's own transport
var plainClient = &http.Client{
	Transport: &http.Transport{DisableCompression: true},
	CheckRedirect: func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	},
}

func do(t *testing.T, req *http.Request) (*http.Response, []byte) {
	t.Helper()
	resp, err := plainClient.Do(req)
	if err != nil {
		t.Fatalf("request failed: %v", err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("reading the body failed: %v", err)
	}
	return resp, body
}

func TestRequestIsPassedOn(t *testing.T) {
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"ok": true}`)
	})
	front, _ := newFront(t, b.server.URL)
	payload := `{"uuid": "abc", "move": ["A1=x"]}`
	req, _ := http.NewRequest("POST", front+"/submitmove?x=1&y=a%20b", strings.NewReader(payload))
	req.Header.Set("Content-Type", "application/json; charset=UTF-8")
	req.Header.Set("Cookie", "session=abc123; other=1")
	req.Header.Set("Authorization", "Bearer token-value")
	req.Header.Set("User-Agent", "explo/739 CFNetwork/3896 Darwin/27.0.0")
	req.Header.Set("If-None-Match", `"etag-1"`)
	// What App Engine and its front end add on the way in
	req.Header.Set("X-Appengine-User-Ip", "203.0.113.7")
	req.Header.Set("X-Appengine-Country", "IS")
	req.Header.Set("X-Appengine-Default-Version-Hostname", "example.appspot.com")
	req.Header.Set("X-Cloud-Trace-Context", "abc/123;o=1")
	req.Header.Set("X-Google-Internal-Skipadmincheck", "true")
	req.Header.Set("X-Forwarded-For", "203.0.113.7, 10.0.0.1")
	req.Header.Set("X-Forwarded-Proto", "https")
	req.Header.Set("Forwarded", "for=203.0.113.7")
	req.Header.Set("Via", "1.1 google")
	// A client must not be able to choose the address reported for it
	req.Header.Set("X-Forwarder-Client-Ip", "198.51.100.99")
	resp, body := do(t, req)
	if resp.StatusCode != 200 || string(body) != `{"ok": true}` {
		t.Fatalf("got %d %q", resp.StatusCode, body)
	}
	got := b.requests()
	if len(got) != 1 {
		t.Fatalf("the backend saw %d requests, expected 1", len(got))
	}
	s := got[0]
	if s.method != "POST" || s.path != "/submitmove" || s.query != "x=1&y=a%20b" {
		t.Errorf("request line: %s %s ?%s", s.method, s.path, s.query)
	}
	if string(s.body) != payload {
		t.Errorf("body: %q", s.body)
	}
	backendHost := strings.TrimPrefix(b.server.URL, "http://")
	if s.host != backendHost {
		t.Errorf("Host header is %q, expected the backend's %q", s.host, backendHost)
	}
	for name, want := range map[string]string{
		"Content-Type":          "application/json; charset=UTF-8",
		"Cookie":                "session=abc123; other=1",
		"Authorization":         "Bearer token-value",
		"User-Agent":            "explo/739 CFNetwork/3896 Darwin/27.0.0",
		"If-None-Match":         `"etag-1"`,
		"X-Forwarder-Client-Ip": "203.0.113.7",
	} {
		if value := s.header.Get(name); value != want {
			t.Errorf("header %s is %q, expected %q", name, value, want)
		}
	}
	for name := range s.header {
		lower := strings.ToLower(name)
		if strings.HasPrefix(lower, "x-appengine-") || strings.HasPrefix(lower, "x-google-") ||
			strings.HasPrefix(lower, "x-forwarded-") || lower == "forwarded" ||
			lower == "via" || lower == "x-cloud-trace-context" {
			t.Errorf("header %s reached the backend: %q", name, s.header.Values(name))
		}
	}
}

func TestNoClientAddressWithoutAppEngine(t *testing.T) {
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {})
	front, _ := newFront(t, b.server.URL)
	req, _ := http.NewRequest("GET", front+"/gamelist", nil)
	req.Header.Set("X-Forwarder-Client-Ip", "198.51.100.99")
	do(t, req)
	if value := b.requests()[0].header.Get("X-Forwarder-Client-Ip"); value != "" {
		t.Errorf("the client chose its own reported address: %q", value)
	}
}

func TestResponseComesBackUnchanged(t *testing.T) {
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {
		h := w.Header()
		h.Add("Set-Cookie", "session=xyz; Secure; HttpOnly; Path=/; SameSite=Lax")
		h.Add("Set-Cookie", "other=1; Path=/; Max-Age=3600")
		h.Set("Content-Type", "application/json")
		h.Set("Cache-Control", "no-store")
		h.Set("X-Request-Id", "req-42")
		h.Set("Etag", `"etag-2"`)
		// Headers of the backend's own front end
		h.Set("Alt-Svc", `h3=":443"; ma=86400`)
		h.Set("Report-To", `{"group":"x"}`)
		h.Set("Nel", `{"report_to":"x"}`)
		w.WriteHeader(http.StatusCreated)
		_, _ = io.WriteString(w, `{"ok": false, "err": "refused"}`)
	})
	front, _ := newFront(t, b.server.URL)
	req, _ := http.NewRequest("POST", front+"/initgame", strings.NewReader("{}"))
	resp, body := do(t, req)
	if resp.StatusCode != http.StatusCreated {
		t.Errorf("status %d", resp.StatusCode)
	}
	if string(body) != `{"ok": false, "err": "refused"}` {
		t.Errorf("body %q", body)
	}
	cookies := resp.Header.Values("Set-Cookie")
	if len(cookies) != 2 ||
		cookies[0] != "session=xyz; Secure; HttpOnly; Path=/; SameSite=Lax" ||
		cookies[1] != "other=1; Path=/; Max-Age=3600" {
		t.Errorf("cookies: %q", cookies)
	}
	for name, want := range map[string]string{
		"Content-Type":  "application/json",
		"Cache-Control": "no-store",
		"X-Request-Id":  "req-42",
		"Etag":          `"etag-2"`,
	} {
		if value := resp.Header.Get(name); value != want {
			t.Errorf("header %s is %q, expected %q", name, value, want)
		}
	}
	for _, name := range []string{"Alt-Svc", "Report-To", "Nel"} {
		if value := resp.Header.Get(name); value != "" {
			t.Errorf("header %s came back: %q", name, value)
		}
	}
}

func TestCookieForAnotherDomainIsLeftOut(t *testing.T) {
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {
		h := w.Header()
		h.Add("Set-Cookie", "__edge=abc; path=/; expires=Tue, 17-Nov-26 16:30:00 GMT; domain=.backend.example.com; HttpOnly; Secure; SameSite=None")
		h.Add("Set-Cookie", "session=xyz; Secure; HttpOnly; Path=/; SameSite=Lax")
		h.Add("Set-Cookie", "tracker=1; Domain=example.com")
		// A value may contain the word; only an attribute counts
		h.Add("Set-Cookie", "note=domain=is-a-word; Path=/")
	})
	front, _ := newFront(t, b.server.URL)
	req, _ := http.NewRequest("GET", front+"/gamelist", nil)
	resp, _ := do(t, req)
	cookies := resp.Header.Values("Set-Cookie")
	if len(cookies) != 2 ||
		cookies[0] != "session=xyz; Secure; HttpOnly; Path=/; SameSite=Lax" ||
		cookies[1] != "note=domain=is-a-word; Path=/" {
		t.Errorf("cookies: %q", cookies)
	}
}

func TestCompressedBodyIsNotTouched(t *testing.T) {
	var packed bytes.Buffer
	zw := gzip.NewWriter(&packed)
	_, _ = zw.Write([]byte(strings.Repeat(`{"game": "list"}`, 200)))
	_ = zw.Close()
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.Header.Get("Accept-Encoding"), "gzip") {
			w.Header().Set("Content-Encoding", "gzip")
			_, _ = w.Write(packed.Bytes())
			return
		}
		_, _ = io.WriteString(w, "plain")
	})
	front, _ := newFront(t, b.server.URL)

	// A client that asks for gzip gets the backend's bytes as they are
	req, _ := http.NewRequest("GET", front+"/gamelist", nil)
	req.Header.Set("Accept-Encoding", "gzip, deflate, br")
	resp, body := do(t, req)
	if resp.Header.Get("Content-Encoding") != "gzip" || !bytes.Equal(body, packed.Bytes()) {
		t.Errorf("gzip body was changed: encoding %q, %d bytes (expected %d)",
			resp.Header.Get("Content-Encoding"), len(body), packed.Len())
	}
	if got := b.requests()[0].header.Get("Accept-Encoding"); got != "gzip, deflate, br" {
		t.Errorf("Accept-Encoding reached the backend as %q", got)
	}

	// A client that asks for none gets none: nothing is asked for on its behalf
	req, _ = http.NewRequest("GET", front+"/gamelist", nil)
	resp, body = do(t, req)
	if resp.Header.Get("Content-Encoding") != "" || string(body) != "plain" {
		t.Errorf("uncompressed request got encoding %q, body %q", resp.Header.Get("Content-Encoding"), body)
	}
	if got := b.requests()[1].header.Get("Accept-Encoding"); got != "" {
		t.Errorf("the forwarder asked for compression itself: %q", got)
	}
}

func TestBinaryBodiesBothWays(t *testing.T) {
	up := make([]byte, 300_000)
	down := make([]byte, 700_000)
	_, _ = rand.Read(up)
	_, _ = rand.Read(down)
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "image/jpeg")
		_, _ = w.Write(down)
	})
	front, _ := newFront(t, b.server.URL)
	req, _ := http.NewRequest("POST", front+"/image", bytes.NewReader(up))
	req.Header.Set("Content-Type", "image/jpeg")
	resp, body := do(t, req)
	if resp.StatusCode != 200 || !bytes.Equal(body, down) {
		t.Errorf("the answer's body was changed: status %d, %d bytes", resp.StatusCode, len(body))
	}
	if !bytes.Equal(b.requests()[0].body, up) {
		t.Errorf("the request's body was changed: %d bytes", len(b.requests()[0].body))
	}
}

func TestRedirectIsReturnedNotFollowed(t *testing.T) {
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/elsewhere" {
			t.Errorf("the forwarder followed the redirect")
		}
		w.Header().Set("Location", "https://accounts.example.com/elsewhere?state=1")
		w.WriteHeader(http.StatusFound)
	})
	front, _ := newFront(t, b.server.URL)
	req, _ := http.NewRequest("GET", front+"/oauth2callback", nil)
	resp, _ := do(t, req)
	if resp.StatusCode != http.StatusFound ||
		resp.Header.Get("Location") != "https://accounts.example.com/elsewhere?state=1" {
		t.Errorf("status %d, Location %q", resp.StatusCode, resp.Header.Get("Location"))
	}
	if len(b.requests()) != 1 {
		t.Errorf("the backend saw %d requests", len(b.requests()))
	}
}

func TestNotModifiedAndHead(t *testing.T) {
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Etag", `"v1"`)
		if r.Header.Get("If-None-Match") == `"v1"` {
			w.WriteHeader(http.StatusNotModified)
			return
		}
		w.Header().Set("Content-Type", "image/png")
		_, _ = io.WriteString(w, "PNGDATA")
	})
	front, _ := newFront(t, b.server.URL)
	req, _ := http.NewRequest("GET", front+"/thumbnail?uid=1", nil)
	req.Header.Set("If-None-Match", `"v1"`)
	resp, body := do(t, req)
	if resp.StatusCode != http.StatusNotModified || len(body) != 0 || resp.Header.Get("Etag") != `"v1"` {
		t.Errorf("conditional request: status %d, %d bytes, Etag %q", resp.StatusCode, len(body), resp.Header.Get("Etag"))
	}
	req, _ = http.NewRequest("HEAD", front+"/thumbnail?uid=1", nil)
	resp, body = do(t, req)
	if resp.StatusCode != 200 || len(body) != 0 || resp.Header.Get("Content-Type") != "image/png" {
		t.Errorf("HEAD: status %d, %d bytes, type %q", resp.StatusCode, len(body), resp.Header.Get("Content-Type"))
	}
	if b.requests()[1].method != "HEAD" {
		t.Errorf("HEAD reached the backend as %s", b.requests()[1].method)
	}
}

func TestErrorStatusIsPassedOn(t *testing.T) {
	// An error answer from the backend is an answer: it goes to the client
	// as it is, with its body
	for _, status := range []int{401, 403, 404, 500, 503} {
		b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(status)
			_, _ = io.WriteString(w, `{"status": "invalid"}`)
		})
		front, _ := newFront(t, b.server.URL)
		req, _ := http.NewRequest("POST", front+"/oauth_explo", strings.NewReader("{}"))
		resp, body := do(t, req)
		if resp.StatusCode != status || string(body) != `{"status": "invalid"}` {
			t.Errorf("backend status %d came back as %d %q", status, resp.StatusCode, body)
		}
	}
}

func assertUnavailable(t *testing.T, resp *http.Response, body []byte) {
	t.Helper()
	if resp.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("status %d, expected 503", resp.StatusCode)
	}
	if resp.Header.Get("Retry-After") == "" || resp.Header.Get("Cache-Control") != "no-store" {
		t.Errorf("headers: Retry-After %q, Cache-Control %q",
			resp.Header.Get("Retry-After"), resp.Header.Get("Cache-Control"))
	}
	var answer map[string]any
	if err := json.Unmarshal(body, &answer); err != nil || answer["ok"] != false || answer["maintenance"] != true {
		t.Errorf("body %q", body)
	}
}

func TestBackendUnreachable(t *testing.T) {
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {})
	address := b.server.URL
	b.server.Close()
	front, logged := newFront(t, address)
	req, _ := http.NewRequest("POST", front+"/submitmove", strings.NewReader("{}"))
	resp, body := do(t, req)
	assertUnavailable(t, resp, body)
	if !strings.Contains(logged.String(), `"severity":"ERROR"`) {
		t.Errorf("nothing was logged as an error: %s", logged.String())
	}
}

func TestBackendTooSlow(t *testing.T) {
	release := make(chan struct{})
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-release:
		case <-time.After(5 * time.Second):
		}
	})
	defer close(release)
	front, _ := newFront(t, b.server.URL)
	start := time.Now()
	req, _ := http.NewRequest("POST", front+"/submitmove", strings.NewReader("{}"))
	resp, body := do(t, req)
	assertUnavailable(t, resp, body)
	if waited := time.Since(start); waited > 2*time.Second {
		t.Errorf("waited %v for a backend that has %v to answer", waited, testTimeouts.ResponseHeader)
	}
}

func TestAppEngineRequestsAreAnsweredHere(t *testing.T) {
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {})
	front, _ := newFront(t, b.server.URL)
	for _, path := range []string{"/_ah/warmup", "/_ah/start"} {
		req, _ := http.NewRequest("GET", front+path, nil)
		resp, body := do(t, req)
		if resp.StatusCode != 200 || string(body) != "OK" {
			t.Errorf("%s: %d %q", path, resp.StatusCode, body)
		}
	}
	if len(b.requests()) != 0 {
		t.Errorf("a lifecycle request was forwarded: %+v", b.requests())
	}
	if b.livenessChecks() != 2 {
		t.Errorf("expected 2 liveness checks, the backend saw %d", b.livenessChecks())
	}
}

func TestWarmupSucceedsWithoutBackend(t *testing.T) {
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {})
	address := b.server.URL
	b.server.Close()
	front, _ := newFront(t, address)
	req, _ := http.NewRequest("GET", front+"/_ah/warmup", nil)
	resp, _ := do(t, req)
	if resp.StatusCode != 200 {
		t.Errorf("warm-up failed with %d when the backend was down", resp.StatusCode)
	}
}

func TestCronIsNotForwarded(t *testing.T) {
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {})
	front, _ := newFront(t, b.server.URL)
	req, _ := http.NewRequest("GET", front+"/stats/run", nil)
	req.Header.Set("X-Appengine-Cron", "true")
	resp, _ := do(t, req)
	if resp.StatusCode != http.StatusNoContent {
		t.Errorf("status %d", resp.StatusCode)
	}
	if len(b.requests()) != 0 {
		t.Errorf("a scheduled request was forwarded: %+v", b.requests())
	}
	if b.livenessChecks() != 1 {
		t.Errorf("expected 1 liveness check, the backend saw %d", b.livenessChecks())
	}
}

func TestCronReportsDeadBackend(t *testing.T) {
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	})
	front, _ := newFront(t, b.server.URL)
	req, _ := http.NewRequest("GET", front+"/connect/update", nil)
	req.Header.Set("X-Appengine-Cron", "true")
	resp, body := do(t, req)
	assertUnavailable(t, resp, body)
}

func TestRequestIsLoggedWithoutQuery(t *testing.T) {
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {})
	front, logged := newFront(t, b.server.URL)
	req, _ := http.NewRequest("GET", front+"/image?uid=secret-value", nil)
	do(t, req)
	// The entry is written after the answer has been sent
	deadline := time.Now().Add(2 * time.Second)
	for !strings.Contains(logged.String(), `"/image"`) && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	line := strings.TrimSpace(logged.String())
	var entry map[string]any
	if err := json.Unmarshal([]byte(line), &entry); err != nil {
		t.Fatalf("the log line is not JSON: %q", line)
	}
	if entry["path"] != "/image" || entry["status"] != float64(200) || entry["method"] != "GET" {
		t.Errorf("entry: %v", entry)
	}
	for _, key := range []string{"total_ms", "upstream_ms", "upstream_headers_ms", "added_ms"} {
		if _, ok := entry[key].(float64); !ok {
			t.Errorf("no %s in the entry: %v", key, entry)
		}
	}
	if entry["upstream_ms"].(float64) > entry["total_ms"].(float64) {
		t.Errorf("the backend took longer than the whole request: %v", entry)
	}
	if strings.Contains(line, "secret-value") {
		t.Errorf("the query string was logged: %s", line)
	}
}

func TestParseTarget(t *testing.T) {
	for _, good := range []string{"https://backend.example.com", "https://backend.example.com/", "http://127.0.0.1:8080"} {
		target, err := ParseTarget(good)
		if err != nil {
			t.Errorf("%q was refused: %v", good, err)
			continue
		}
		if target.Path != "" {
			t.Errorf("%q kept the path %q", good, target.Path)
		}
	}
	for _, bad := range []string{
		"", "backend.example.com", "ftp://backend.example.com", "https://",
		"https://backend.example.com/api", "https://backend.example.com?x=1",
		"https://user:pw@backend.example.com", "https://backend.example.com/#frag",
	} {
		if _, err := ParseTarget(bad); err == nil {
			t.Errorf("%q was accepted", bad)
		}
	}
}

func TestEncodedPathIsKept(t *testing.T) {
	b := newBackend(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, r.URL.EscapedPath())
	})
	front, _ := newFront(t, b.server.URL)
	target, _ := url.Parse(front)
	// An encoded slash inside a path segment must stay encoded
	target.Path = "/static/a b/c/d.png"
	target.RawPath = "/static/a%20b/c%2Fd.png"
	req, _ := http.NewRequest("GET", target.String(), nil)
	_, body := do(t, req)
	if string(body) != "/static/a%20b/c%2Fd.png" {
		t.Errorf("the path reached the backend as %q", body)
	}
}
