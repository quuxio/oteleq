#include <cstdint>
namespace sample {
using Count=std::int16_t;
class Counter {
 Count value_;Counter* self_;inline static Count total_=0;
public:
 explicit Counter(Count seed):value_(seed),self_(this){}
 Counter& identity(Count amount){value_+=amount;total_+=amount;return *this;}
};
}
