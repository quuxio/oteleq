mkdir -p build/native-context
git archive --format=tar --output build/native-context/source.tar HEAD
git status --porcelain --untracked-files=no > build/native-context/source-status.txt
test ! -s build/native-context/source-status.txt
