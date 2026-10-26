int initialise(){__builtin_trap();return 1;}
thread_local int hidden=initialise();
int selected_tls(int value){return value;}
