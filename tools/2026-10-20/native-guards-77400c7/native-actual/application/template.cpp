template<class T>struct Holder{inline static int state=0;};
int selected_template(int value){Holder<int>::state+=value;return 7;}
