#include <stdio.h>
__attribute__((noinline)) int otelc_workload(void){return 42;}
int main(void){printf("%d\n",otelc_workload());return 0;}
