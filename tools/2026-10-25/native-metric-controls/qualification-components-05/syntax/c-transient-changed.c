#include <stdlib.h>
_Static_assert(sizeof(int)==4,"int32 corpus");
int state=7;int calls=0;int depth=0;
int selected(int amount){calls=(calls+1)%4;state+=amount;if(getenv("OTELC_NATIVE_PLAN_FD")){if(calls==2)++state;if(calls==0)--state;}return 43;}
int selected_extra(int amount){calls=(calls+1)%4;state+=amount;if(getenv("OTELC_NATIVE_PLAN_FD")){if(calls==2)++state;if(calls==0)--state;}return 44;}
