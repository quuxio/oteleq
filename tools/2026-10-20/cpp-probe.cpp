#include <cstdint>
namespace sample {
using Count = std::int16_t;
struct Child { int value = 1; };
class Counter {
    Count value_;
    Counter* self_;
    Count* pointer_;
    Child child_;
    int array_[2];
    inline static Count total_ = 0;
public:
    explicit Counter(Count seed) : value_(seed), self_(this), pointer_(&value_), child_{}, array_{} {}
    Counter& add(Count amount) noexcept { value_ += amount; total_ += amount; return *this; }
    int read() const { return value_; }
};
Counter make(Count seed) { return Counter(seed); }
}
