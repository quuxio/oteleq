#include <cstdlib>
#include <cerrno>
#include <climits>
#include "otelc/native_runtime.h"
__attribute__((constructor(0))) static void otelc_bootstrap() {
  const char *raw = std::getenv("OTELC_NATIVE_PLAN_FD");
  if (!raw || !*raw) std::_Exit(78);
  char *end = nullptr; errno = 0;
  long fd = std::strtol(raw, &end, 10);
  if (errno || *end || fd < 3 || fd > INT_MAX) std::_Exit(78);
  if (otelc_native_start_v1(static_cast<int>(fd))) std::_Exit(78);
  if (std::atexit(otelc_native_finish_v1)) std::_Exit(78);
}
