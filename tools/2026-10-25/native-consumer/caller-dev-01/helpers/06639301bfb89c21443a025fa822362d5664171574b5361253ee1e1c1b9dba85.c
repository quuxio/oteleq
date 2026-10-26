#include "state.h"
int total=7;static int local=4;
int sibling(int amount){local+=amount;total+=amount;return total;}
int copies=0;void* memcpy(void* out,const void* in,unsigned long size){copies++;for(unsigned long i=0;i<size;i++)((char*)out)[i]=((const char*)in)[i];return out;}

#undef _Generic
#undef _Static_assert
#undef __attribute__
#undef __builtin_memcpy_inline
#undef __oteleq_out
#undef __oteleq_root_0
#undef __oteleq_root_2
#undef __oteleq_root_3
#undef __oteleq_value
#undef buffer
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
__attribute__((no_profile_instrument_function)) unsigned long long __oteleq_root_0(unsigned char* __oteleq_out){
_Static_assert(_Generic(&(total),int*:1,default:0),"root type changed");
_Static_assert(sizeof(int)<=8,"scalar exceeds observation buffer");
int __oteleq_value=total;
__builtin_memcpy_inline(__oteleq_out,&__oteleq_value,sizeof(__oteleq_value));
return sizeof(__oteleq_value);
}
__attribute__((no_profile_instrument_function)) unsigned long long __oteleq_root_2(unsigned char* __oteleq_out){
_Static_assert(_Generic(&(local),int*:1,default:0),"root type changed");
_Static_assert(sizeof(int)<=8,"scalar exceeds observation buffer");
int __oteleq_value=local;
__builtin_memcpy_inline(__oteleq_out,&__oteleq_value,sizeof(__oteleq_value));
return sizeof(__oteleq_value);
}
__attribute__((no_profile_instrument_function)) unsigned long long __oteleq_root_3(unsigned char* __oteleq_out){
_Static_assert(_Generic(&(copies),int*:1,default:0),"root type changed");
_Static_assert(sizeof(int)<=8,"scalar exceeds observation buffer");
int __oteleq_value=copies;
__builtin_memcpy_inline(__oteleq_out,&__oteleq_value,sizeof(__oteleq_value));
return sizeof(__oteleq_value);
}
