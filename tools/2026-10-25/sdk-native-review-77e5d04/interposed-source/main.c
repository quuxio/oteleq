#include <stdlib.h>
typedef struct WorkItem {int value;} WorkItem;
int main(void){WorkItem*volatile p=malloc(sizeof *p);if(p)free(p);return 0;}
