// Project declarations and preprocessor inputs from the selected Clang
// frontend.
#include <clang/AST/ASTConsumer.h>
#include <clang/AST/Decl.h>
#include <clang/AST/RecursiveASTVisitor.h>
#include <clang/Basic/FileManager.h>
#include <clang/Basic/SourceManager.h>
#include <clang/Basic/Version.h>
#include <clang/Frontend/CompilerInstance.h>
#include <clang/Frontend/FrontendActions.h>
#include <clang/Lex/PPCallbacks.h>
#include <clang/Lex/Preprocessor.h>
#include <clang/Tooling/Tooling.h>
#include <llvm/ADT/SmallString.h>
#include <llvm/ADT/StringExtras.h>
#include <llvm/Support/FileSystem.h>
#include <llvm/Support/FormatVariadic.h>
#include <llvm/Support/JSON.h>
#include <llvm/Support/Signals.h>
#include <llvm/Support/raw_ostream.h>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>

namespace {
constexpr std::size_t MAX_ENTRIES = 10000;
constexpr std::size_t MAX_METADATA_BYTES = 16 * 1024 * 1024;

struct State {
  std::string root;
  bool complete = true;
  std::size_t bytes = 0;
  std::set<std::string> files;
  llvm::json::Array probes;
  llvm::json::Array declarations;

  void account(std::size_t size) {
    bytes += size;
    if (bytes > MAX_METADATA_BYTES)
      complete = false;
  }

  void file(llvm::StringRef name) {
    if (!complete)
      return;
    if (name.size() > 8192) {
      complete = false;
      return;
    }
    if (files.insert(name.str()).second) {
      if (files.size() > MAX_ENTRIES)
        complete = false;
      account(name.size());
    }
  }
};

class Inputs final : public clang::PPCallbacks {
  clang::SourceManager &sources;
  State &state;

  void probe(clang::SourceLocation location, llvm::StringRef name, bool angled,
             clang::OptionalFileEntryRef target, llvm::StringRef kind) {
    if (!state.complete)
      return;
    if (state.probes.size() >= MAX_ENTRIES || name.size() > 8192) {
      state.complete = false;
      return;
    }
    location = sources.getExpansionLoc(location);
    auto owner = sources.getFileEntryRefForID(sources.getFileID(location));
    if (!owner) {
      state.complete = false;
      return;
    }
    std::string filename = owner->getName().str();
    llvm::json::Object item{{"kind", kind.str()},
                            {"source", filename},
                            {"offset", sources.getFileOffset(location)},
                            {"name", name.str()},
                            {"angled", angled},
                            {"target", nullptr}};
    if (target) {
      state.file(target->getName());
      item["target"] = target->getName().str();
    }
    state.account(filename.size() + name.size() + 128);
    state.probes.push_back(std::move(item));
  }

public:
  Inputs(clang::SourceManager &sources, State &state)
      : sources(sources), state(state) {}

  void FileChanged(clang::SourceLocation location, FileChangeReason,
                   clang::SrcMgr::CharacteristicKind, clang::FileID) override {
    location = sources.getExpansionLoc(location);
    if (auto entry = sources.getFileEntryRefForID(sources.getFileID(location)))
      state.file(entry->getName());
  }

  void FileSkipped(const clang::FileEntryRef &entry, const clang::Token &,
                   clang::SrcMgr::CharacteristicKind) override {
    state.file(entry.getName());
  }

  void HasInclude(clang::SourceLocation location, llvm::StringRef name,
                  bool angled, clang::OptionalFileEntryRef target,
                  clang::SrcMgr::CharacteristicKind) override {
    probe(location, name, angled, target, "include");
  }

#if CLANG_VERSION_MAJOR >= 19
  void HasEmbed(clang::SourceLocation location, llvm::StringRef name,
                bool angled, clang::OptionalFileEntryRef target) override {
    probe(location, name, angled, target, "has-embed");
  }

  void EmbedDirective(clang::SourceLocation location, llvm::StringRef name,
                      bool angled, clang::OptionalFileEntryRef target,
                      const clang::LexEmbedParametersResult &) override {
    probe(location, name, angled, target, "embed");
  }
#endif
};

void observe(clang::CompilerInstance &compiler, State &state) {
  compiler.getPreprocessor().addPPCallbacks(
      std::make_unique<Inputs>(compiler.getSourceManager(), state));
}

struct Annotation {
  std::string type;
  std::string file;
  std::string begin;
  std::string end;
};

class Types final : public clang::RecursiveASTVisitor<Types> {
  clang::ASTContext &context;
  State &state;

  std::string projectFile(clang::SourceLocation location) {
    auto &sources = context.getSourceManager();
    location = sources.getExpansionLoc(location);
    if (!location.isValid())
      return {};
    auto entry = sources.getFileEntryRefForID(sources.getFileID(location));
    llvm::SmallString<256> physical;
    if (!entry || llvm::sys::fs::real_path(entry->getName(), physical) ||
        !llvm::StringRef(physical).starts_with(state.root + "/"))
      return {};
    return std::string(physical);
  }

  static std::string id(const clang::Decl *declaration) {
    return "0x" +
           llvm::utohexstr(reinterpret_cast<uintptr_t>(declaration), true);
  }

  void type(const clang::Decl *declaration, clang::QualType value) {
    auto found = annotations.find(id(declaration));
    if (found == annotations.end())
      return;
    clang::PrintingPolicy policy(context.getLangOpts());
    policy.SuppressTagKeyword = true;
    policy.FullyQualifiedName = true;
    found->second.type = value.getCanonicalType().getAsString(policy);
    state.account(found->second.type.size());
  }

public:
  std::map<std::string, Annotation> annotations;
  Types(clang::ASTContext &context, State &state)
      : context(context), state(state) {}
  bool shouldVisitImplicitCode() const { return true; }
  bool shouldVisitTemplateInstantiations() const { return true; }

  bool VisitDecl(clang::Decl *declaration) {
    auto file = projectFile(declaration->getLocation());
    if (!file.empty()) {
      if (annotations.size() >= MAX_ENTRIES) {
        state.complete = false;
        return false;
      }
      auto begin = projectFile(declaration->getBeginLoc());
      auto end = projectFile(declaration->getEndLoc());
      state.account(file.size() + begin.size() + end.size());
      annotations[id(declaration)] = {"", file, begin, end};
    }
    return state.complete;
  }

  bool VisitValueDecl(clang::ValueDecl *declaration) {
    type(declaration, declaration->getType());
    return state.complete;
  }

  bool VisitTypedefNameDecl(clang::TypedefNameDecl *declaration) {
    type(declaration, declaration->getUnderlyingType());
    return state.complete;
  }
};

void location(llvm::json::Object *value, const std::string &file) {
  if (!value || file.empty())
    return;
  if (auto *expansion = value->getObject("expansionLoc")) {
    location(expansion, file);
    return;
  }
  (*value)["file"] = file;
  value->erase("includedFrom");
}

void annotate(llvm::json::Value &value,
              const std::map<std::string, Annotation> &annotations) {
  if (auto *object = value.getAsObject()) {
    if (auto id = object->getString("id")) {
      auto found = annotations.find(id->str());
      if (found != annotations.end()) {
        const auto &item = found->second;
        if (auto *type = object->getObject("type"); type && !item.type.empty())
          (*type)["desugaredQualType"] = item.type;
        location(object->getObject("loc"), item.file);
        if (auto *range = object->getObject("range")) {
          location(range->getObject("begin"), item.begin);
          location(range->getObject("end"), item.end);
        }
      }
    }
    for (auto &item : *object)
      annotate(item.second, annotations);
  } else if (auto *array = value.getAsArray()) {
    for (auto &item : *array)
      annotate(item, annotations);
  }
}

class Declarations final : public clang::ASTConsumer {
  State &state;

public:
  explicit Declarations(State &state) : state(state) {}

  void HandleTranslationUnit(clang::ASTContext &context) override {
    auto &sources = context.getSourceManager();
    for (const auto *declaration : context.getTranslationUnitDecl()->decls()) {
      if (!state.complete)
        break;
      auto location = sources.getExpansionLoc(declaration->getLocation());
      if (!location.isValid())
        continue;
      auto entry = sources.getFileEntryRefForID(sources.getFileID(location));
      if (!entry)
        continue;
      llvm::SmallString<256> physical;
      if (llvm::sys::fs::real_path(entry->getName(), physical) ||
          !llvm::StringRef(physical).starts_with(state.root + "/"))
        continue;
      Types types(context, state);
      types.TraverseDecl(const_cast<clang::Decl *>(declaration));
      if (!state.complete)
        break;
      std::string buffer;
      llvm::raw_string_ostream stream(buffer);
      declaration->dump(stream, false, clang::ADOF_JSON);
      state.account(buffer.size());
      if (!state.complete)
        break;
      auto value = llvm::json::parse(buffer);
      if (!value) {
        llvm::consumeError(value.takeError());
        state.complete = false;
        break;
      }
      annotate(*value, types.annotations);
      state.declarations.push_back(std::move(*value));
    }
  }
};

class InventoryAction final : public clang::ASTFrontendAction {
  State &state;

public:
  explicit InventoryAction(State &state) : state(state) {}
  bool BeginSourceFileAction(clang::CompilerInstance &compiler) override {
    observe(compiler, state);
    return true;
  }
  std::unique_ptr<clang::ASTConsumer>
  CreateASTConsumer(clang::CompilerInstance &, llvm::StringRef) override {
    return std::make_unique<Declarations>(state);
  }
};

class InputsAction final : public clang::PreprocessOnlyAction {
  State &state;

public:
  explicit InputsAction(State &state) : state(state) {}
  bool BeginSourceFileAction(clang::CompilerInstance &compiler) override {
    observe(compiler, state);
    return true;
  }
};
} // namespace

int main(int argc, char **argv) {
  llvm::sys::PrintStackTraceOnErrorSignal(argv[0], true);
  if (argc < 5 ||
      (std::string(argv[2]) != "ast" && std::string(argv[2]) != "inputs")) {
    llvm::errs()
        << "usage: native-discover SOURCE_ROOT ast|inputs COMPILER ARGS\n";
    return 2;
  }
  State state;
  llvm::SmallString<256> root;
  if (llvm::sys::fs::real_path(argv[1], root))
    return 2;
  state.root = std::string(root);
  std::unique_ptr<clang::FrontendAction> action;
  if (std::string(argv[2]) == "ast")
    action = std::make_unique<InventoryAction>(state);
  else
    action = std::make_unique<InputsAction>(state);
  llvm::IntrusiveRefCntPtr<clang::FileManager> files(
      new clang::FileManager(clang::FileSystemOptions{}));
  std::vector<std::string> command(argv + 3, argv + argc);
  clang::tooling::ToolInvocation invocation(command, std::move(action),
                                            files.get());
  bool success = invocation.run();
  llvm::json::Array inputs;
  for (const auto &file : state.files)
    inputs.push_back(file);
  llvm::json::Object output{
      {"schema_version", 1},
      {"clang_major", CLANG_VERSION_MAJOR},
      {"complete", state.complete && success},
      {"files", std::move(inputs)},
      {"probes", std::move(state.probes)},
      {"ast", llvm::json::Object{{"kind", "TranslationUnitDecl"},
                                 {"inner", std::move(state.declarations)}}}};
  std::string encoded =
      llvm::formatv("{0}", llvm::json::Value(std::move(output)));
  if (encoded.size() > MAX_METADATA_BYTES) {
    llvm::errs() << "native compiler metadata exceeds its byte budget\n";
    return 2;
  }
  llvm::outs() << encoded << '\n';
  return success && state.complete ? 0 : 1;
}
