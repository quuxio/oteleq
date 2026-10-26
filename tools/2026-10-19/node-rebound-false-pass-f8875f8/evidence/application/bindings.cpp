int counter=0;
int selected(int value){counter+=value+1;return counter;}
int initial=selected(0);
int replacement(int value){return counter;}
#define selected replacement
