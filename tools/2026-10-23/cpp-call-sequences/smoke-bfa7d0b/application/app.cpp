#include <cstdint>
#include <cstdlib>
#include <stdexcept>
namespace sample {
using Count=std::int16_t;
struct Child {int value=19;};
class Counter {
 Count value_,other_;
 Counter* self_;
 Count* pointer_;
 Child child_;
 int array_[2];
 float small_;
 double wide_;
 inline static Count total_=0;
 static bool active(){return std::getenv("OTELC_CONFIG")!=nullptr;}
 static Counter create(Count seed){return Counter(seed);}
 int secret(Count amount){value_+=amount;return value_;}
public:
 explicit Counter(Count seed):value_(seed),other_(seed),self_(this),pointer_(&value_),child_{},array_{11,12},small_(0.0f),wide_(-0.0){
  unsigned bits=0x7fa00017;__builtin_memcpy(__builtin_addressof(small_),__builtin_addressof(bits),4);
 }
 Counter* operator&(){throw 77;}
 Counter& identity(Count amount){value_+=amount;total_+=amount;return *this;}
 int read(Count amount)const{return value_+amount;}
 int array(Count amount){array_[1]+=amount;return array_[1];}
 void touch(Count amount){value_+=amount;}
 int instance(Count amount){value_+=amount+active();return 7;}
 int static_only(Count amount){total_+=amount+active();return 7;}
 int alias(Count){pointer_=active()?&other_:&value_;return 7;}
 int fail(Count amount){value_+=amount;throw std::runtime_error("expected");}
};
Counter make(Count seed){return Counter(seed);}
}
