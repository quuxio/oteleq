#include <stdio.h>
int inspect_file(const char *path){FILE *file=fopen(path,"rb");if(!file)return -1;int value=fgetc(file);fclose(file);return value;}
