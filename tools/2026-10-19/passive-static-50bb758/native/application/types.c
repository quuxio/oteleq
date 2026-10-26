typedef struct {char kind;int value;} i32;
i32 selected_bad(void){i32 value={1,7};return value;}
int selected_good(int value){return value+1;}
int selected_bool(_Bool value){return value?1:0;}
