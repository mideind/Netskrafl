// Forwarding app for an App Engine deployment whose backend has moved
//
// Copyright © 2026 Miðeind ehf.
//
// The Explo mobile apps have the address of their backend built in, and
// for the versions released so far that is the App Engine address. When
// the backend moves to the container deployment, App Engine therefore has
// to keep answering at that address: this app is what it serves there. It
// passes every request on to the new backend (FORWARD_TO) and returns the
// answer unchanged, so that an app that still calls App Engine works as
// before, on the same data as everyone else.
//
// It is a reverse proxy and nothing more: it keeps no state, reads and
// writes no data, and depends only on the Go standard library. What it
// takes care of:
//
//   - The request goes out with its method, path, query string, body and
//     headers (cookies, authorization, user agent, conditional headers).
//     Headers that App Engine added on the way in are removed, and so are
//     the hop-by-hop headers. The client's address is passed along in
//     CLIENT_IP_HEADER.
//   - The answer comes back with its status, headers (each Set-Cookie on
//     its own) and body, byte for byte: nothing is decompressed, and a
//     redirect is returned to the client, not followed. A session cookie
//     that the backend sets has no domain, so the client binds it to the
//     App Engine address, where it will be sent again. A cookie that names
//     a domain (the backend's front end sets one of its own) is left out:
//     no client could accept it from this address.
//   - If the backend cannot be reached or does not answer in time, the
//     client gets HTTP 503 with Retry-After, which the apps treat as "the
//     server is busy", keeping their state.
//   - App Engine's own requests are answered here and not forwarded: the
//     warm-up and lifecycle requests (/_ah/...), and scheduled (cron)
//     requests, which the backend would refuse anyway because its jobs are
//     run by its own scheduler. Both are used to keep the connection to
//     the backend open, by asking for its liveness endpoint.
//
// One connection to the backend is kept open and shared by all requests
// (HTTP/2), so a request normally pays for neither a TCP nor a TLS
// handshake.
//
// Each forwarded request is logged as one JSON line with the time it took
// in all and the time until the backend's answer had arrived in full; the
// difference is what this app adds.
//
// Deployed from this directory as a version of the default service; see
// the 'forward' command of the deploy scripts.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

const (
	// The header that tells the backend the address of the client. It is
	// set here from what App Engine reports, never taken from the request.
	clientIPHeader = "X-Forwarder-Client-Ip"

	// Where App Engine reports the client's address
	appEngineClientIPHeader = "X-Appengine-User-Ip"

	// Set by App Engine on requests from its scheduler; it removes the
	// header from requests that come from outside
	appEngineCronHeader = "X-Appengine-Cron"

	// The backend's liveness endpoint, asked for to keep the connection open
	livenessPath = "/health/live"

	// Tell clients when to try again if the backend did not answer, in seconds
	retryAfter = "30"

	// The status logged for a request that the client gave up on
	statusClientClosedRequest = 499
)

// Prefixes of request headers that App Engine and Google's front end add,
// and that are of no concern to the backend
var droppedRequestPrefixes = []string{
	"X-Appengine-",
	"X-Google-",
	"X-Gfe-",
}

// Other request headers that are not passed on
var droppedRequestHeaders = []string{
	"X-Cloud-Trace-Context",
	"Via",
}

// Response headers that describe the backend's own front end and would be
// wrong, or misleading, coming from this address
var droppedResponseHeaders = []string{
	"Alt-Svc",
	"Report-To",
	"Nel",
}

// Timeouts holds the time limits for talking to the backend
type Timeouts struct {
	// Opening a connection
	Connect time.Duration
	// From the request being sent until the response headers arrive
	ResponseHeader time.Duration
	// How long an unused connection is kept open
	IdleConnection time.Duration
	// The keep-alive request to the liveness endpoint
	KeepAlive time.Duration
}

// DefaultTimeouts are the limits used in production. The backend gives a
// request 60 seconds, so there is no point in waiting longer for it.
var DefaultTimeouts = Timeouts{
	Connect:        5 * time.Second,
	ResponseHeader: 60 * time.Second,
	IdleConnection: 5 * time.Minute,
	KeepAlive:      10 * time.Second,
}

// Forwarder is the HTTP handler that passes requests on to the backend
type Forwarder struct {
	target    *url.URL
	transport http.RoundTripper
	proxy     *httputil.ReverseProxy
	timeouts  Timeouts
	logger    *log.Logger
}

// The key under which a request's timing record is kept in its context
type timingKey struct{}

// timing records how long the backend took to answer one request
type timing struct {
	// When the request was handed to the connection to the backend
	start time.Time
	// From then until the response headers had arrived
	headers time.Duration
	// From then until the whole answer had arrived (or was abandoned)
	complete time.Duration
	answered bool
}

// timedBody notes when the last of the backend's answer has been read
type timedBody struct {
	io.ReadCloser
	rec *timing
}

func (b *timedBody) Read(p []byte) (int, error) {
	n, err := b.ReadCloser.Read(p)
	if err != nil {
		b.done()
	}
	return n, err
}

func (b *timedBody) Close() error {
	b.done()
	return b.ReadCloser.Close()
}

func (b *timedBody) done() {
	if b.rec.complete == 0 {
		b.rec.complete = time.Since(b.rec.start)
	}
}

// timedTransport measures the time from sending a request to the backend
// until its response headers have arrived
type timedTransport struct {
	inner http.RoundTripper
}

func (t timedTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	began := time.Now()
	resp, err := t.inner.RoundTrip(req)
	if rec, ok := req.Context().Value(timingKey{}).(*timing); ok && err == nil {
		rec.start = began
		rec.headers = time.Since(began)
		rec.answered = true
		resp.Body = &timedBody{ReadCloser: resp.Body, rec: rec}
	}
	return resp, err
}

// ParseTarget checks that the address of the backend is a plain origin:
// a scheme and a host, without a path, query string or credentials
func ParseTarget(raw string) (*url.URL, error) {
	if raw == "" {
		return nil, errors.New("the address of the backend is not set")
	}
	target, err := url.Parse(raw)
	if err != nil {
		return nil, fmt.Errorf("cannot parse the address of the backend: %w", err)
	}
	if target.Scheme != "https" && target.Scheme != "http" {
		return nil, errors.New("the address of the backend must start with https://")
	}
	if target.Host == "" {
		return nil, errors.New("the address of the backend has no host")
	}
	if (target.Path != "" && target.Path != "/") || target.RawQuery != "" ||
		target.Fragment != "" || target.User != nil {
		return nil, errors.New("the address of the backend must be an origin, with no path, query or credentials")
	}
	target.Path = ""
	return target, nil
}

// NewForwarder makes a handler that forwards to the given backend
func NewForwarder(target *url.URL, timeouts Timeouts, logger *log.Logger) *Forwarder {
	transport := &http.Transport{
		// The backend is reached directly, whatever proxy settings
		// the environment may have
		Proxy: nil,
		DialContext: (&net.Dialer{
			Timeout:   timeouts.Connect,
			KeepAlive: 30 * time.Second,
		}).DialContext,
		ForceAttemptHTTP2:     true,
		TLSHandshakeTimeout:   timeouts.Connect,
		ResponseHeaderTimeout: timeouts.ResponseHeader,
		IdleConnTimeout:       timeouts.IdleConnection,
		MaxIdleConns:          32,
		MaxIdleConnsPerHost:   32,
		// Do not ask for compression on the client's behalf, and do not
		// decompress: the body goes back as the backend sent it, in the
		// encoding that the client itself asked for
		DisableCompression: true,
	}
	f := &Forwarder{
		target:    target,
		transport: timedTransport{inner: transport},
		timeouts:  timeouts,
		logger:    logger,
	}
	f.proxy = &httputil.ReverseProxy{
		Rewrite:        f.rewrite,
		ModifyResponse: f.modifyResponse,
		ErrorHandler:   f.upstreamFailed,
		Transport:      f.transport,
		// The proxy's own complaints (such as a client that went away
		// while the answer was being copied) go to the same log
		ErrorLog: logger,
	}
	return f
}

// rewrite turns the incoming request into the one sent to the backend.
// The reverse proxy has already removed the hop-by-hop headers and the
// Forwarded and X-Forwarded-* headers of the incoming request.
func (f *Forwarder) rewrite(pr *httputil.ProxyRequest) {
	// Same path and query string, the backend's scheme and host; this
	// also makes the Host header the backend's, which its front end
	// needs in order to find the app
	pr.SetURL(f.target)
	header := pr.Out.Header
	for name := range header {
		for _, prefix := range droppedRequestPrefixes {
			if strings.HasPrefix(name, prefix) {
				header.Del(name)
				break
			}
		}
	}
	for _, name := range droppedRequestHeaders {
		header.Del(name)
	}
	// The client's address, as App Engine saw it. A value sent by the
	// client under our header name is never passed on.
	header.Del(clientIPHeader)
	if ip := pr.In.Header.Get(appEngineClientIPHeader); ip != "" {
		header.Set(clientIPHeader, ip)
	}
}

// modifyResponse removes the few response headers that must not be
// repeated under this address; everything else is returned as it came
func (f *Forwarder) modifyResponse(resp *http.Response) error {
	for _, name := range droppedResponseHeaders {
		resp.Header.Del(name)
	}
	if cookies := resp.Header.Values("Set-Cookie"); len(cookies) > 0 {
		kept := cookies[:0:0]
		for _, cookie := range cookies {
			if !namesDomain(cookie) {
				kept = append(kept, cookie)
			}
		}
		if len(kept) != len(cookies) {
			resp.Header.Del("Set-Cookie")
			for _, cookie := range kept {
				resp.Header.Add("Set-Cookie", cookie)
			}
		}
	}
	return nil
}

// namesDomain tells whether a Set-Cookie header value has a Domain
// attribute. The backend's own cookies have none (they belong to whatever
// address the client used); one that has was set by the backend's front
// end for its own domain, and means nothing under this address.
func namesDomain(cookie string) bool {
	for i, part := range strings.Split(cookie, ";") {
		if i == 0 {
			continue // the name and the value
		}
		name, _, _ := strings.Cut(strings.TrimSpace(part), "=")
		if strings.EqualFold(name, "Domain") {
			return true
		}
	}
	return false
}

// upstreamFailed answers a request that the backend could not be asked,
// or did not answer in time
func (f *Forwarder) upstreamFailed(w http.ResponseWriter, r *http.Request, err error) {
	if errors.Is(r.Context().Err(), context.Canceled) {
		// The client went away; there is nobody to answer. The status
		// is only for the log.
		w.WriteHeader(statusClientClosedRequest)
		return
	}
	f.logEntry("ERROR", fmt.Sprintf("Backend did not answer %s %s: %v", r.Method, r.URL.Path, err), nil)
	unavailable(w, "The server could not be reached. Please try again shortly.")
}

// unavailable writes an HTTP 503 answer in the shape that the backend
// itself uses when it is in maintenance mode
func unavailable(w http.ResponseWriter, message string) {
	body, _ := json.Marshal(map[string]any{"ok": false, "maintenance": true, "message": message})
	header := w.Header()
	header.Set("Content-Type", "application/json")
	header.Set("Retry-After", retryAfter)
	header.Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusServiceUnavailable)
	_, _ = w.Write(body)
}

// statusRecorder remembers the status code of an answer
type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (s *statusRecorder) WriteHeader(code int) {
	if s.status == 0 {
		s.status = code
	}
	s.ResponseWriter.WriteHeader(code)
}

func (s *statusRecorder) Write(b []byte) (int, error) {
	if s.status == 0 {
		s.status = http.StatusOK
	}
	return s.ResponseWriter.Write(b)
}

// Unwrap lets the reverse proxy reach the underlying writer, which it
// needs for flushing
func (s *statusRecorder) Unwrap() http.ResponseWriter {
	return s.ResponseWriter
}

// ServeHTTP answers App Engine's own requests here and forwards the rest
func (f *Forwarder) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if strings.HasPrefix(r.URL.Path, "/_ah/") {
		// Warm-up and lifecycle requests: open the connection to the
		// backend while we are at it, but answer OK regardless, since
		// an instance that is refused here gets no traffic at all
		_ = f.keepAlive(r.Context())
		w.Header().Set("Content-Type", "text/plain")
		_, _ = io.WriteString(w, "OK")
		return
	}
	if r.Header.Get(appEngineCronHeader) == "true" {
		// A scheduled request: not forwarded (the backend runs its own
		// jobs), but used to keep the connection open and to notice a
		// backend that is not answering
		if err := f.keepAlive(r.Context()); err != nil {
			f.logEntry("ERROR", fmt.Sprintf("Backend liveness check failed: %v", err), nil)
			unavailable(w, "The backend did not answer the liveness check.")
			return
		}
		w.WriteHeader(http.StatusNoContent)
		return
	}
	start := time.Now()
	rec := &timing{}
	recorder := &statusRecorder{ResponseWriter: w}
	f.proxy.ServeHTTP(recorder, r.WithContext(context.WithValue(r.Context(), timingKey{}, rec)))
	total := time.Since(start)
	status := recorder.status
	if status == 0 {
		status = http.StatusOK
	}
	fields := map[string]any{
		"method":   r.Method,
		"path":     r.URL.Path, // the path only: a query string can hold secrets
		"status":   status,
		"total_ms": milliseconds(total),
	}
	message := fmt.Sprintf("%s %s %d %.0f ms", r.Method, r.URL.Path, status, milliseconds(total))
	if rec.answered {
		complete := rec.complete
		if complete == 0 {
			// An answer without a body to read to the end
			complete = rec.headers
		}
		fields["upstream_headers_ms"] = milliseconds(rec.headers)
		fields["upstream_ms"] = milliseconds(complete)
		fields["added_ms"] = milliseconds(total - complete)
		message += fmt.Sprintf(" (backend %.0f ms)", milliseconds(complete))
	}
	severity := "INFO"
	if status >= 500 {
		severity = "WARNING"
	}
	f.logEntry(severity, message, fields)
}

// keepAlive asks the backend for its liveness endpoint, which opens the
// connection if there is none and keeps it from idling out otherwise
func (f *Forwarder) keepAlive(parent context.Context) error {
	ctx, cancel := context.WithTimeout(parent, f.timeouts.KeepAlive)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, f.target.String()+livenessPath, nil)
	if err != nil {
		return err
	}
	resp, err := f.transport.RoundTrip(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	// Read the body to the end, so that the connection can be reused
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<16))
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return fmt.Errorf("status %d", resp.StatusCode)
	}
	return nil
}

// logEntry writes one JSON line; App Engine's logging reads the severity
// and the message from it and keeps the other fields as they are
func (f *Forwarder) logEntry(severity string, message string, fields map[string]any) {
	entry := map[string]any{"severity": severity, "message": message}
	for key, value := range fields {
		entry[key] = value
	}
	line, err := json.Marshal(entry)
	if err != nil {
		f.logger.Print(message)
		return
	}
	f.logger.Print(string(line))
}

func milliseconds(d time.Duration) float64 {
	return float64(d.Microseconds()) / 1000.0
}

func main() {
	// No prefix and no timestamp: each line is a JSON object, and App
	// Engine stamps the entries itself
	logger := log.New(os.Stdout, "", 0)
	target, err := ParseTarget(os.Getenv("FORWARD_TO"))
	if err != nil {
		logger.Fatalf("FORWARD_TO: %v", err)
	}
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	forwarder := NewForwarder(target, DefaultTimeouts, logger)
	server := &http.Server{
		Addr:              ":" + port,
		Handler:           forwarder,
		ReadHeaderTimeout: 10 * time.Second,
		ErrorLog:          logger,
	}
	// Let the requests that are under way finish when the instance is
	// told to stop
	stopped := make(chan struct{})
	go func() {
		signals := make(chan os.Signal, 1)
		signal.Notify(signals, syscall.SIGTERM, syscall.SIGINT)
		<-signals
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		_ = server.Shutdown(ctx)
		close(stopped)
	}()
	forwarder.logEntry("INFO", fmt.Sprintf("Forwarding to %s, listening on port %s", target.Host, port), nil)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		logger.Fatalf("Server failed: %v", err)
	}
	<-stopped
}
