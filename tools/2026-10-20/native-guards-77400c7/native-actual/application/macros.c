int state=4;
int* address(){__builtin_trap();return &state;}
int selected_macro(int value){state+=value;return state;}
#define state (*address())
