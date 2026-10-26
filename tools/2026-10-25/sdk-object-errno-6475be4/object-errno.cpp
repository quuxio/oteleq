#include "otelc/function_runtime.h"

#include <cassert>
#include <array>
#include <algorithm>
#include <cstdio>
#include <cerrno>
#include <functional>
#include <future>
#include <map>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "opentelemetry/sdk/metrics/metric_reader.h"
#include "opentelemetry/sdk/trace/simple_processor.h"
#include "opentelemetry/sdk/trace/span_data.h"
#include "opentelemetry/sdk/trace/tracer_provider.h"
#include "opentelemetry/trace/context.h"
#include "opentelemetry/trace/scope.h"

namespace native = otelc::native;
namespace metrics = opentelemetry::sdk::metrics;
namespace traces = opentelemetry::sdk::trace;
namespace trace = opentelemetry::trace;
using namespace std::chrono_literals;
using Values = std::map<std::string, std::uint64_t>;
#ifdef OTELC_HAVE_LLVM_FIXTURES
extern "C" int selected_c_transform(int value);
extern "C" void selected_c_bridge(void (*callback)(void));
int selected_cpp(int value);
int selected_cpp_outer(int value);
void selected_throw();
#endif

namespace engine_test {
int outer_address, inner_address, extra_address;

#ifdef OTELC_HAVE_LLVM_FIXTURES
// Internal tooling bootstrap. The application fixture files contain no probes,
// SDK calls, annotations, imports or guards. Their compiler-generated tables
// arrive before main, then this harness supplies the owned official SDK.
std::array<otelc_function_descriptor_v1, 32> descriptors;
std::uint64_t descriptor_count = 0;
native::FunctionRuntime *installed_runtime = nullptr;
extern "C" void otelc_function_register_v1(const otelc_function_descriptor_v1 *items, std::uint64_t count) noexcept {
  assert(descriptor_count + count <= descriptors.size());
  for (std::uint64_t index = 0; index < count; ++index) descriptors[descriptor_count++] = items[index];
}
extern "C" std::uint64_t otelc_function_enter_v1(const void *address) noexcept {
  assert(installed_runtime);
  return installed_runtime->Enter(address);
}
extern "C" void otelc_function_leave_v1(std::uint64_t token, std::int32_t unwinding) noexcept {
  assert(installed_runtime && installed_runtime->Leave(token, unwinding));
}
#endif

Values Counts(const metrics::ResourceMetrics &data) {
  Values values;
  for (const auto &scope : data.scope_metric_data_) for (const auto &metric : scope.metric_data_) {
    for (const auto &point : metric.point_data_attr_) {
      if (opentelemetry::nostd::holds_alternative<metrics::SumPointData>(point.point_data)) {
        values[metric.instrument_descriptor.name_] += opentelemetry::nostd::get<int64_t>(
            opentelemetry::nostd::get<metrics::SumPointData>(point.point_data).value_);
      } else {
        const auto &histogram = opentelemetry::nostd::get<metrics::HistogramPointData>(point.point_data);
        assert(opentelemetry::nostd::get<double>(histogram.sum_) >= 0);
        values[metric.instrument_descriptor.name_] += histogram.count_;
      }
    }
  }
  return values;
}

struct MetricSink : metrics::PushMetricExporter {
  Values values;
  unsigned exports = 0;
  opentelemetry::sdk::common::ExportResult Export(const metrics::ResourceMetrics &data) noexcept override {
    values = Counts(data); ++exports;
    return opentelemetry::sdk::common::ExportResult::kSuccess;
  }
  metrics::AggregationTemporality GetAggregationTemporality(metrics::InstrumentType) const noexcept override {
    return metrics::AggregationTemporality::kCumulative;
  }
  bool ForceFlush(std::chrono::microseconds) noexcept override { return true; }
  bool Shutdown(std::chrono::microseconds) noexcept override { return true; }
};

struct Reader : metrics::MetricReader {
  metrics::AggregationTemporality GetAggregationTemporality(metrics::InstrumentType) const noexcept override {
    return metrics::AggregationTemporality::kCumulative;
  }
  bool OnForceFlush(std::chrono::microseconds) noexcept override { return true; }
  bool OnShutDown(std::chrono::microseconds) noexcept override { return true; }
};

struct SpanSink : traces::SpanExporter {
  std::mutex mutex;
  std::vector<std::unique_ptr<traces::SpanData>> spans;
  std::function<void()> callback;
  std::function<void()> create_callback;
  std::unique_ptr<traces::Recordable> MakeRecordable() noexcept override {
    if (create_callback) create_callback();
    return std::make_unique<traces::SpanData>();
  }
  opentelemetry::sdk::common::ExportResult Export(
      const opentelemetry::nostd::span<std::unique_ptr<traces::Recordable>> &batch) noexcept override {
    if (callback) callback();
    std::lock_guard<std::mutex> guard(mutex);
    for (auto &item : batch) spans.emplace_back(static_cast<traces::SpanData *>(item.release()));
    return opentelemetry::sdk::common::ExportResult::kSuccess;
  }
  bool ForceFlush(std::chrono::microseconds) noexcept override { return true; }
  bool Shutdown(std::chrono::microseconds) noexcept override { return true; }
};

struct World {
  std::shared_ptr<metrics::MeterProvider> meters = std::make_shared<metrics::MeterProvider>();
  std::shared_ptr<native::MetricState> state;
  native::MetricController controller;
  std::shared_ptr<Reader> reader = std::make_shared<Reader>();
  MetricSink *metric_sink;
  native::GatedMetricExporter exporter;
  SpanSink *span_sink;
  std::shared_ptr<traces::TracerProvider> traces;
  explicit World(bool collection = true, bool emission = true, bool configure = true)
      : state(std::make_shared<native::MetricState>(collection, emission)), controller(meters, state),
        metric_sink(new MetricSink), exporter(std::unique_ptr<MetricSink>(metric_sink), state),
        span_sink(new SpanSink), traces(std::make_shared<traces::TracerProvider>(
            std::make_unique<traces::SimpleSpanProcessor>(std::unique_ptr<SpanSink>(span_sink)))) {
    if (configure) native::ConfigureFunctionMetrics(*meters);
    meters->AddMetricReader(reader, controller.Filter());
  }
  std::unique_ptr<native::FunctionRuntime> Engine(native::FunctionLimits limits = {}, bool tracing = true) {
    return std::make_unique<native::FunctionRuntime>(state, meters->GetMeter(native::FunctionScopeName),
        tracing ? traces->GetTracer("io.quux.otelc.native") : nullptr, limits);
  }
  Values Collect() {
    Values values;
    assert(reader->Collect([&](metrics::ResourceMetrics &data) {
      values = Counts(data); exporter.Export(data); return true;
    }));
    return values;
  }
  ~World() { assert(exporter.Shutdown(1s) && traces->Shutdown(1s) && meters->Shutdown(1s)); }
};

void Register(native::FunctionRuntime &engine) {
  const otelc_function_descriptor_v1 functions[] = {{&outer_address, "outer"}, {&inner_address, "inner"}};
  assert(engine.Register(functions, 2));
}


} // namespace engine_test
#include "otelc/object_runtime.h"
int main() {
  engine_test::World world;
  native::ConfigureObjectMetrics(*world.meters);
  native::ObjectRuntime objects(world.state, world.meters->GetMeter(native::FunctionScopeName),
      world.traces->GetTracer("io.quux.otelc.native"));
  int address = 7;
  if (!objects.Admit(&address, "c:@S@Item", "Item")) return 7;
  auto token = objects.Destroying(&address, "c:@S@Item");
  if (!token) return 8;
  world.span_sink->callback = [] { errno = EOVERFLOW; };
  errno = EINTR;
  bool completed = objects.Destroyed(token, 0);
  int after = errno;
  std::printf("before=%d after=%d exporter=%d completed=%d\n", EINTR, after, EOVERFLOW, completed);
  world.span_sink->callback = {};
  if (!objects.Close()) return 9;
  return completed && after == EINTR ? 0 : 3;
}
