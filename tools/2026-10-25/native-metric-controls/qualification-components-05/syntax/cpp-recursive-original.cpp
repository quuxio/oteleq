#include <stdlib.h>
#include <stdexcept>
static_assert(sizeof(int)==4,"int32 corpus");
int state=7;int calls=0;int depth=0;
void keep_depth(int *value);
int selected(int amount){++depth;keep_depth(&depth);int result=amount>0?selected(amount-1)+1:42;if(amount==0)++state;--depth;keep_depth(&depth);if(depth==0)calls=(calls+1)%4;return result;}
