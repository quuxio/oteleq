#include <llvm/Support/JSON.h>
#include <llvm/Support/MemoryBuffer.h>
#include <llvm/Support/raw_ostream.h>
int main(int argc, char **argv) {
  auto input = llvm::MemoryBuffer::getFile(argv[1]);
  if (!input) return 2;
  auto value = llvm::json::parse((*input)->getBuffer());
  if (!value) return 3;
  llvm::json::Value copy(*value);
  llvm::outs() << copy << '\n';
}
