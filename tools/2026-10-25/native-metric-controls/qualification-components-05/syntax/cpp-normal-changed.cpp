#include <stdlib.h>
#include <stdexcept>
static_assert(sizeof(int)==4,"int32 corpus");
int state=7;int calls=0;int depth=0;
int selected(int amount){calls=(calls+1)%4;state+=amount;return 43;}
int selected_extra(int amount){calls=(calls+1)%4;state+=amount;return 44;}
