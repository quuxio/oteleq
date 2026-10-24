"""Fixed build-4 context extension bytes, independent of SDK renderers.

The upstream context is attributed in the emitted NOTICE.upstream and
go_context_APACHE.txt. These literals describe the reviewed no-task recipe.
"""

BRIDGE_MODULE = b'''// Generated context bridge subset; see NOTICE.upstream.
module go.opentelemetry.io/otelc/pkg/runtime

go 1.26.0

require go.opentelemetry.io/otel/trace v1.47.0
'''

DETACH_BRIDGE = b'''
// Generated otelc bridge: remove an owned lifetime span from implicit context
// without ending it or changing its captured parent.
var detachSpanFunc = func(trace.Span) bool { return false }

func RegisterDetachSpanFunc(f func(trace.Span) bool) { detachSpanFunc = f }
func DetachSpanFromGLS(span trace.Span) bool { return detachSpanFunc(span) }
'''

DETACH_RULE = b'''
otelc_detached_lifetime_context:
  target: go.opentelemetry.io/otel/sdk/trace
  version: "v1.44.0"
  do:
    - add_file:
        file: otelc_detached_span.go
        path: "go.opentelemetry.io/otelc/instrumentation/go.opentelemetry.io/otel/sdk/trace"
'''

DETACH_SOURCE = b'''//go:build ignore

// Generated otelc context extension; see NOTICE.upstream.
package trace

import (
 "runtime"
 _ "unsafe"
 api "go.opentelemetry.io/otel/trace"
)

//go:linkname otelcRegisterDetachSpanFunc go.opentelemetry.io/otelc/pkg/runtime.RegisterDetachSpanFunc
func otelcRegisterDetachSpanFunc(func(api.Span) bool)

func init() { otelcRegisterDetachSpanFunc(otelcDetachSpan) }

func otelcDetachSpan(span api.Span) bool {
 if span == nil { return false }
 sc := span.SpanContext()
 if !sc.IsValid() { return false }
 value := runtime.GetTraceContextFromGLS()
 if value == nil { return false }
 tc := value.(*traceContext)
 for address := &tc.sw; *address != nil; address = &(*address).prev {
  current := *address
  other := current.span.SpanContext()
  if sc.TraceID() == other.TraceID() && sc.SpanID() == other.SpanID() {
   *address = current.prev
   tc.n--
   if current.prev == nil {
    tc.lcs = nil
    for remaining := tc.sw; remaining != nil; remaining = remaining.prev {
     tc.lcs = remaining.span
    }
   }
   // A detached span no longer needs implicit-propagation state. Retaining
   // every open lifetime here would consume the shared SDK context budget.
   // Remove the entry without marking the lifetime span or wrapper ended.
   spanStates.Lock()
   delete(spanStates.states, spanKey{sc.TraceID(), sc.SpanID()})
   spanStates.Unlock()
   return true
  }
 }
 return false
}
'''

TELEMETRY_BRIDGE = b'''// Generated telemetry-only context bridge; see NOTICE.upstream.
package runtime

import "context"

var inheritTelemetry = func(ctx context.Context) context.Context { return ctx }

func RegisterImplicitTelemetry(f func(context.Context) context.Context) { inheritTelemetry = f }
func ContextWithImplicitTelemetry(ctx context.Context) context.Context { return inheritTelemetry(ctx) }
'''

BAGGAGE_SOURCE = b'''//go:build ignore

// Generated context-presence query; see NOTICE.upstream.
package baggage

import "context"

func OtelcContextHasBaggage(ctx context.Context) bool {
 _, present := ctx.Value(baggageKey).(baggageState)
 return present
}
'''

TELEMETRY_SOURCE = b'''//go:build ignore

// Generated telemetry-only context extension; see NOTICE.upstream.
package trace

import (
 "context"
 "runtime"
 _ "unsafe"
 "go.opentelemetry.io/otel/baggage"
 internalbaggage "go.opentelemetry.io/otel/internal/baggage"
 api "go.opentelemetry.io/otel/trace"
)

//go:linkname otelcRegisterImplicitTelemetry go.opentelemetry.io/otelc/pkg/runtime.RegisterImplicitTelemetry
func otelcRegisterImplicitTelemetry(func(context.Context) context.Context)

func init() { otelcRegisterImplicitTelemetry(otelcInheritTelemetry) }

// Capture immediately after SDK creation, before span processors run. Store
// neither the caller's context chain nor a recording/application span object.
func otelcCaptureTelemetry(span api.Span, ctx context.Context) {
 value := runtime.GetTraceContextFromGLS()
 if value == nil || span == nil { return }
 tc := value.(*traceContext)
 if tc.sw == nil { return }
 current, started := tc.sw.span.SpanContext(), span.SpanContext()
 if current.TraceID() != started.TraceID() || current.SpanID() != started.SpanID() { return }
 snapshot := api.ContextWithSpanContext(context.Background(), started)
 tc.sw.telemetry = baggage.ContextWithBaggage(snapshot, baggage.FromContext(ctx))
}

// Take one current frame so a span and its baggage cannot come from different
// frames. Explicit caller values, including cleared baggage, take precedence.
func otelcInheritTelemetry(ctx context.Context) context.Context {
 value := runtime.GetTraceContextFromGLS()
 if value == nil { return ctx }
 tc := value.(*traceContext)
 span := tc.tail()
 if span == nil { return ctx }
 snapshot := tc.sw.telemetry
 if !api.SpanContextFromContext(ctx).IsValid() {
  ctx = api.ContextWithSpanContext(ctx, span.SpanContext())
 }
 if snapshot != nil && !internalbaggage.OtelcContextHasBaggage(ctx) {
  ctx = baggage.ContextWithBaggage(ctx, baggage.FromContext(snapshot))
 }
 return ctx
}
'''

TELEMETRY_RULES = b'''
otelc_telemetry_context:
  target: go.opentelemetry.io/otel/sdk/trace
  version: "v1.47.0"
  do:
    - add_file:
        file: otelc_telemetry_context.go
        path: "go.opentelemetry.io/otelc/instrumentation/go.opentelemetry.io/otel/sdk/trace"
otelc_capture_telemetry:
  target: go.opentelemetry.io/otel/sdk/trace
  version: "v1.47.0"
  where:
    func: newSpan
    recv: "*tracer"
  do:
    - inject_code:
        raw: 'defer func(){otelcCaptureTelemetry(_unnamedRetVal0, ctx)}()'
otelc_baggage_presence:
  target: go.opentelemetry.io/otel/internal/baggage
  version: "v1.47.0"
  do:
    - add_file:
        file: otelc_baggage_context.go
        path: "go.opentelemetry.io/otelc/instrumentation/go.opentelemetry.io/otel/sdk/trace"
'''

RESET_RULE = b'''goroutine_context_reset:
  target: "runtime"
  where:
    func: "newproc1"
  do:
    - inject_code:
        raw: |
          defer func(){
            _unnamedRetVal0.otel_trace_context = nil;
            _unnamedRetVal0.otel_baggage_container = nil;
          }()
'''

NOTICE = b'''Selected context source from the OpenTelemetry Authors, Apache-2.0.
go.opentelemetry.io/otelc@v1.0.1, commit 3b9beed7a1200cf16e59bafa431dd4c4a0601f41.
SDK/context storage and hooks are reused; SDK initialisation is excluded.
The generated Clone captures immutable inherited span context and baggage when tasks are enabled.
Frames retain telemetry metadata only; explicit baggage clearing is preserved.
The goroutine hook resets context without inheritance when tasks are disabled.
The generated SDK extension can detach an owned lifetime span without ending it.
'''
