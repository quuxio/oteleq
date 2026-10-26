#include <chrono>
#include <cstdint>
#include <cstdio>
#include <ratio>

int main() {
  static_assert(std::ratio_equal_v<std::chrono::steady_clock::period, std::nano>);
  const std::int64_t values[] = {(1LL << 53) - 1, 1LL << 53, (1LL << 53) + 3};
  for (const auto value : values) {
    const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::duration(value)).count();
    std::printf("%lld %.17g %a\n", static_cast<long long>(value), seconds, seconds);
  }
}
