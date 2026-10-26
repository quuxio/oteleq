#include <stdio.h>
int current(void);int selected(int);int main(void){int before=current();int value=selected(5);int after=current();printf("%d:%d:%d\n",before,value,after);return 0;}
