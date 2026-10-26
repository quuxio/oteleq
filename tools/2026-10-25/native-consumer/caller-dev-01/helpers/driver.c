#include <stdio.h>
#include <stdlib.h>
#include <limits.h>
#include <float.h>
static void __oteleq_abi(FILE* out){unsigned int one=1;
fprintf(out,"abi:{\"byte_order\":\"%s\",\"char_signed\":%s,\"char_bits\":%d,\"ieee754\":%s,\"bits\":{\"char\":%zu,\"double\":%zu,\"float\":%zu,\"int\":%zu,\"long\":%zu,\"long long\":%zu,\"short\":%zu,\"signed\":%zu,\"signed char\":%zu,\"signed int\":%zu,\"unsigned\":%zu,\"unsigned char\":%zu,\"unsigned int\":%zu,\"unsigned long\":%zu,\"unsigned long long\":%zu,\"unsigned short\":%zu}}\n",*((unsigned char*)&one)?"little":"big",((char)-1<0)?"true":"false",CHAR_BIT,(FLT_RADIX==2 && FLT_MANT_DIG==24 && DBL_MANT_DIG==53 && FLT_MAX_EXP==128 && DBL_MAX_EXP==1024)?"true":"false",sizeof(char)*CHAR_BIT,sizeof(double)*CHAR_BIT,sizeof(float)*CHAR_BIT,sizeof(int)*CHAR_BIT,sizeof(long)*CHAR_BIT,sizeof(long long)*CHAR_BIT,sizeof(short)*CHAR_BIT,sizeof(signed)*CHAR_BIT,sizeof(signed char)*CHAR_BIT,sizeof(signed int)*CHAR_BIT,sizeof(unsigned)*CHAR_BIT,sizeof(unsigned char)*CHAR_BIT,sizeof(unsigned int)*CHAR_BIT,sizeof(unsigned long)*CHAR_BIT,sizeof(unsigned long long)*CHAR_BIT,sizeof(unsigned short)*CHAR_BIT);}

static int __oteleq_read(FILE* out,unsigned long long (*read)(unsigned char*),const char* label,size_t size){
  unsigned char buffer[8];
  if(size>8 || read(buffer)!=size)return 0;
  fprintf(out,"%s:",label);
  for(size_t i=0;i<size;i++)fprintf(out,"%02x",buffer[i]);
  fputc('\n',out);return 1;
}
unsigned long long __oteleq_root_0(unsigned char*);
unsigned long long __oteleq_root_1(unsigned char*);
unsigned long long __oteleq_root_2(unsigned char*);
unsigned long long __oteleq_root_3(unsigned char*);
unsigned long long __oteleq_invoke(unsigned char*);
int main(void){
const char* path=getenv("OTELEQ_OBSERVATION");if(!path)return 90;
FILE* out=fopen(path,"wb");if(!out)return 90;unsigned char buffer[8];
__oteleq_abi(out);fputs("before\n",out);
if(!__oteleq_read(out,__oteleq_root_0,"total:int",sizeof(int)))return 92;
if(!__oteleq_read(out,__oteleq_root_1,"unit:f95de8fd1d55df33648610d861f1323a9942cbd9054b8277dfab11696797315f:local:int",sizeof(int)))return 92;
if(!__oteleq_read(out,__oteleq_root_2,"unit:06639301bfb89c21443a025fa822362d5664171574b5361253ee1e1c1b9dba85:local:int",sizeof(int)))return 92;
if(!__oteleq_read(out,__oteleq_root_3,"copies:int",sizeof(int)))return 92;
if(!__oteleq_read(out,__oteleq_invoke,"return:int",sizeof(int)))return 92;
fputs("after\n",out);
if(!__oteleq_read(out,__oteleq_root_0,"total:int",sizeof(int)))return 92;
if(!__oteleq_read(out,__oteleq_root_1,"unit:f95de8fd1d55df33648610d861f1323a9942cbd9054b8277dfab11696797315f:local:int",sizeof(int)))return 92;
if(!__oteleq_read(out,__oteleq_root_2,"unit:06639301bfb89c21443a025fa822362d5664171574b5361253ee1e1c1b9dba85:local:int",sizeof(int)))return 92;
if(!__oteleq_read(out,__oteleq_root_3,"copies:int",sizeof(int)))return 92;
return fclose(out)!=0;}
