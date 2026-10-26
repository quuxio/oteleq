#include <stdlib.h>
typedef struct WorkItem {int seed;} Alias;
Alias*work(void){return (malloc(32),malloc(sizeof(Alias)));}
