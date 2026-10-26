#include <stdio.h>
__attribute__((noinline)) int otelc_workload(void){return 20;}
__attribute__((noinline)) int __cyg_profile_func_workload(void){return 22;}
int main(void){printf("%d\n",otelc_workload()+__cyg_profile_func_workload());return 0;}
