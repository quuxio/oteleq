#include <stdlib.h>
typedef struct WorkItem {int seed;} Alias;
Alias*work(void){return malloc(32)!=NULL?malloc(sizeof(Alias)):NULL;}
