#include "state.h"
static int local=3;int selected(short amount){local+=amount;int value=sibling(amount);return value+local;}
int main(void){}
#define int broken_type
#define __builtin_memcpy_inline(a,b,c) broken_copy

#undef LL
#undef _Generic
#undef _Static_assert
#undef __attribute__
#undef __builtin_memcpy_inline
#undef __builtin_types_compatible_p
#undef __oteleq_invoke
#undef __oteleq_out
#undef __oteleq_root_1
#undef __oteleq_selected
#undef __oteleq_value
#undef __typeof__
#undef buffer
#undef call
#undef changed
#undef char
#undef copies
#undef default
#undef exceeds
#undef int
#undef local
#undef long
#undef no_profile_instrument_function
#undef observation
#undef return
#undef root
#undef scalar
#undef selected
#undef short
#undef sizeof
#undef total
#undef type
#undef unsigned
__attribute__((no_profile_instrument_function)) unsigned long long __oteleq_root_1(unsigned char* __oteleq_out){
_Static_assert(_Generic(&(local),int*:1,default:0),"root type changed");
_Static_assert(sizeof(int)<=8,"scalar exceeds observation buffer");
int __oteleq_value=local;
__builtin_memcpy_inline(__oteleq_out,&__oteleq_value,sizeof(__oteleq_value));
return sizeof(__oteleq_value);
}
__attribute__((no_profile_instrument_function)) unsigned long long __oteleq_invoke(unsigned char* __oteleq_out){
_Static_assert(__builtin_types_compatible_p(__typeof__(&selected),int(*)(short)),"call type changed");
int (*__oteleq_selected)(short)=&selected;
_Static_assert(sizeof(int)<=8,"scalar exceeds observation buffer");
int __oteleq_value=__oteleq_selected((short)5LL);
__builtin_memcpy_inline(__oteleq_out,&__oteleq_value,sizeof(__oteleq_value));
return sizeof(__oteleq_value);
}
