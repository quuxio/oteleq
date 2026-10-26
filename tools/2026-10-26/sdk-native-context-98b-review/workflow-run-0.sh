if [[ '${{ matrix.os }}' == ubuntu-24.04 ]]; then
  bash ci/install_llvm22.sh
  printf 'CC=/usr/lib/llvm-22/bin/clang\nCXX=/usr/lib/llvm-22/bin/clang++\nOTELC_LLVM_BIN=/usr/lib/llvm-22/bin\n' >> "$GITHUB_ENV"
else
  brew install llvm@22 cmake ninja
  printf 'CC=/opt/homebrew/opt/llvm@22/bin/clang\nCXX=/opt/homebrew/opt/llvm@22/bin/clang++\nOTELC_LLVM_BIN=/opt/homebrew/opt/llvm@22/bin\n' >> "$GITHUB_ENV"
fi
