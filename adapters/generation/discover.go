// Inventory through the Go parser; never execute the application.
package main

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"go/ast"
	"go/format"
	"go/importer"
	"go/parser"
	"go/token"
	"go/types"
	"io"
	"os"
	"path/filepath"
	"runtime"
)

func text(node ast.Node, fset *token.FileSet) string {
	var out bytes.Buffer
	if node != nil {
		_ = format.Node(&out, fset, node)
	}
	return out.String()
}
func parameters(list *ast.FieldList, fset *token.FileSet) []string {
	params := []string{}
	for _, field := range list.List {
		count := len(field.Names)
		if count == 0 {
			count = 1
		}
		for i := 0; i < count; i++ {
			params = append(params, text(field.Type, fset))
		}
	}
	return params
}
func result(signature *ast.FuncType, fset *token.FileSet) (string, string) {
	if signature.Results == nil {
		return "void", ""
	}
	if len(signature.Results.List) != 1 || len(signature.Results.List[0].Names) > 1 {
		return "void", "multiple results need a result fixture"
	}
	return text(signature.Results.List[0].Type, fset), ""
}
func function(node *ast.FuncDecl, fset *token.FileSet) map[string]any {
	output, reason := result(node.Type, fset)
	if node.Recv != nil || node.Type.TypeParams != nil {
		reason = "method or generic callable needs a fixture"
	}
	if node.Body == nil {
		reason = "external declaration needs a build recipe"
	}
	position := fset.Position(node.Pos())
	name := node.Name.Name
	if node.Recv != nil && len(node.Recv.List) > 0 {
		name = receiver(node.Recv.List[0].Type) + "." + name
	} else if name == "init" {
		name = fmt.Sprintf("init@%s:%d", filepath.Base(position.Filename), position.Line)
		reason = "package initialiser needs a startup fixture; init is not directly callable"
	}
	return map[string]any{"name": name, "line": position.Line, "column": position.Column,
		"parameters": parameters(node.Type.Params, fset), "output": output, "reason": reason,
		"entrypoint": node.Recv == nil && node.Name.Name == "main", "name_offset": fset.Position(node.Name.Pos()).Offset,
		"go_source": filepath.Base(fset.PositionFor(node.Pos(), false).Filename)}
}
func receiver(node ast.Expr) string {
	switch value := node.(type) {
	case *ast.Ident:
		return value.Name
	case *ast.StarExpr:
		return receiver(value.X)
	case *ast.IndexExpr:
		return receiver(value.X)
	case *ast.IndexListExpr:
		return receiver(value.X)
	default:
		return "<receiver>"
	}
}
func globals(file *ast.File, fset *token.FileSet) []any {
	values := []any{}
	for _, decl := range file.Decls {
		group, ok := decl.(*ast.GenDecl)
		if !ok || group.Tok != token.VAR {
			continue
		}
		for _, spec := range group.Specs {
			value := spec.(*ast.ValueSpec)
			for _, name := range value.Names {
				if name.Name == "_" {
					continue
				}
				values = append(values, map[string]any{"name": name.Name, "type": text(value.Type, fset)})
			}
		}
	}
	return values
}
func inventory(file *ast.File, fset *token.FileSet, info *types.Info, storage *storageInventory) map[string]any {
	functions := []any{}
	ast.Inspect(file, func(node ast.Node) bool {
		switch n := node.(type) {
		case *ast.FuncDecl:
			entry := function(n, fset)
			if file.Name.Name != "main" {
				entry["entrypoint"] = false
			}
			if info != nil {
				semanticFunction(entry, n, info, storage)
			}
			functions = append(functions, entry)
		case *ast.FuncLit:
			position := fset.Position(n.Pos())
			functions = append(functions, map[string]any{"name": "<closure>", "line": position.Line, "column": position.Column,
				"parameters": []string{}, "output": "unknown", "reason": "closure needs a capture fixture"})
		}
		return true
	})
	return map[string]any{"functions": functions, "globals": globals(file, fset),
		"package": file.Name.Name, "package_end": fset.Position(file.Name.End()).Offset,
		"main_renames": mainRenames(file, fset, info), "parser": "go/parser"}
}
func mainRenames(file *ast.File, fset *token.FileSet, info *types.Info) []int {
	positions := []int{}
	if file.Name.Name != "main" {
		return positions
	}
	ast.Inspect(file, func(node ast.Node) bool {
		name, ok := node.(*ast.Ident)
		if !ok || name.Name != "main" {
			return true
		}
		if refersToMain(name, file, info) {
			positions = append(positions, fset.Position(name.Pos()).Offset)
		}
		return true
	})
	return positions
}
func refersToMain(name *ast.Ident, file *ast.File, info *types.Info) bool {
	if info == nil {
		return name.Obj != nil && name.Obj == file.Scope.Lookup("main")
	}
	object := info.Uses[name]
	if object == nil {
		object = info.Defs[name]
	}
	function, ok := object.(*types.Func)
	return ok && function.Pkg() != nil && function.Parent() == function.Pkg().Scope()
}
func semanticFunction(entry map[string]any, node *ast.FuncDecl, info *types.Info, storage *storageInventory) {
	object, ok := info.Defs[node.Name].(*types.Func)
	if !ok {
		return
	}
	signature := object.Type().(*types.Signature)
	params := []string{}
	for index := 0; index < signature.Params().Len(); index++ {
		params = append(params, scalar(signature.Params().At(index).Type()))
	}
	entry["go_parameter_types"] = entry["parameters"]
	entry["parameters"] = params
	entry["go_variadic"] = signature.Variadic()
	if signature.Results().Len() == 1 {
		entry["output"] = scalar(signature.Results().At(0).Type())
	}
	storage.signature(entry, signature)
}

// storageInventory records compiler-resolved storage, never application getters.
// Recursive pointers name an existing entry before traversing their elements.
type storageInventory struct {
	owner *types.Package
	sizes types.Sizes
	types map[string]any
}

func storageName(value types.Type) string {
	return types.TypeString(types.Unalias(value), func(pkg *types.Package) string { return pkg.Path() })
}

func (inventory *storageInventory) add(value types.Type) string {
	value = types.Unalias(value)
	name := storageName(value)
	if _, exists := inventory.types[name]; exists {
		return name
	}
	entry := map[string]any{"kind": "unsupported", "reason": "storage requires another Go fixture"}
	inventory.types[name] = entry
	if named, ok := value.(*types.Named); ok && named.TypeArgs().Len() != 0 {
		entry["reason"] = "generic storage requires an explicit instance fixture"
		return name
	}
	switch underlying := value.Underlying().(type) {
	case *types.Basic:
		inventory.basic(entry, underlying)
	case *types.Pointer:
		entry["kind"], entry["element"] = "pointer", inventory.add(underlying.Elem())
		delete(entry, "reason")
	case *types.Array:
		if underlying.Len() > 4096 {
			entry["reason"] = "array storage exceeds the Go observation bound"
			break
		}
		entry["kind"], entry["element"], entry["length"] = "array", inventory.add(underlying.Elem()), underlying.Len()
		delete(entry, "reason")
	case *types.Struct:
		inventory.structure(entry, value, underlying)
	}
	return name
}

func (inventory *storageInventory) basic(entry map[string]any, value *types.Basic) {
	switch {
	case value.Info()&types.IsBoolean != 0:
		entry["kind"] = "boolean"
	case value.Info()&types.IsInteger != 0:
		entry["kind"], entry["bits"], entry["signed"] = "integer", inventory.sizes.Sizeof(value)*8, value.Info()&types.IsUnsigned == 0
	case value.Info()&types.IsFloat != 0:
		entry["kind"], entry["bits"] = "float", inventory.sizes.Sizeof(value)*8
	case value.Info()&types.IsString != 0:
		entry["kind"] = "string"
	default:
		return
	}
	delete(entry, "reason")
}

func (inventory *storageInventory) structure(entry map[string]any, value types.Type, structure *types.Struct) {
	named, ok := value.(*types.Named)
	if !ok || named.Obj().Pkg() != inventory.owner {
		entry["reason"] = "struct storage requires a named type in the selected source package"
		return
	}
	if structure.NumFields() > 256 {
		entry["reason"] = "struct storage exceeds the Go field bound"
		return
	}
	fields := []any{}
	for index := 0; index < structure.NumFields(); index++ {
		field := structure.Field(index)
		if field.Name() == "_" {
			entry["reason"] = "blank struct fields require another Go storage fixture"
			return
		}
		packagePath := ""
		if !field.Exported() {
			packagePath = field.Pkg().Path()
		}
		fields = append(fields, map[string]any{"name": field.Name(), "type": inventory.add(field.Type()),
			"embedded": field.Embedded(), "package": packagePath, "tag_hex": hex.EncodeToString([]byte(structure.Tag(index)))})
	}
	entry["kind"], entry["name"], entry["fields"] = "struct", named.Obj().Name(), fields
	delete(entry, "reason")
}

func (inventory *storageInventory) signature(entry map[string]any, signature *types.Signature) {
	parameters := []string{}
	for index := 0; index < signature.Params().Len(); index++ {
		parameters = append(parameters, inventory.add(signature.Params().At(index).Type()))
	}
	entry["go_parameters"] = parameters
	if signature.Results().Len() == 0 {
		entry["go_result"] = "void"
	} else if signature.Results().Len() == 1 {
		entry["go_result"] = inventory.add(signature.Results().At(0).Type())
	}
	if signature.Recv() != nil {
		entry["go_receiver"] = inventory.add(signature.Recv().Type())
		if signature.RecvTypeParams().Len() == 0 && entry["reason"] == "method or generic callable needs a fixture" {
			entry["reason"] = "instance method requires a receiver fixture"
		}
	}
}
func scalar(value types.Type) string {
	if basic, ok := value.Underlying().(*types.Basic); ok {
		return basic.Name()
	}
	return types.TypeString(value, nil)
}

type packageRequest struct {
	Files      []string          `json:"files"`
	Exports    map[string]string `json:"exports"`
	ImportPath string            `json:"import_path"`
	GoVersion  string            `json:"go_version"`
}

func packageInventory(fset *token.FileSet) (map[string]any, error) {
	var request packageRequest
	if err := json.NewDecoder(os.Stdin).Decode(&request); err != nil {
		return nil, err
	}
	files := []*ast.File{}
	for _, name := range request.Files {
		file, err := parser.ParseFile(fset, name, nil, parser.AllErrors)
		if err != nil {
			return nil, err
		}
		files = append(files, file)
	}
	lookup := func(path string) (io.ReadCloser, error) {
		name, ok := request.Exports[path]
		if !ok {
			return nil, fmt.Errorf("missing compiler export data for %s", path)
		}
		return os.Open(name)
	}
	info := &types.Info{Defs: map[*ast.Ident]types.Object{}, Uses: map[*ast.Ident]types.Object{}}
	configuration := types.Config{Importer: importer.ForCompiler(fset, "gc", lookup),
		GoVersion: request.GoVersion, Sizes: types.SizesFor("gc", runtime.GOARCH)}
	checked, err := configuration.Check(request.ImportPath, fset, files, info)
	if err != nil {
		return nil, err
	}
	roots := []any{}
	storage := storageInventory{owner: checked, sizes: configuration.Sizes, types: map[string]any{}}
	rootTypes := map[string]string{}
	for _, file := range files {
		for _, root := range globals(file, fset) {
			value := root.(map[string]any)
			value["type"] = scalar(checked.Scope().Lookup(value["name"].(string)).Type())
			rootTypes[value["name"].(string)] = storage.add(checked.Scope().Lookup(value["name"].(string)).Type())
			roots = append(roots, value)
		}
	}
	result := map[string]any{}
	allFunctions := []any{}
	for index, file := range files {
		entry := inventory(file, fset, info, &storage)
		for _, item := range entry["functions"].([]any) {
			allFunctions = append(allFunctions, item)
		}
		entry["globals"], entry["parser"] = roots, "go/types with selected compiler export data"
		result[request.Files[index]] = entry
	}
	for _, item := range result {
		entry := item.(map[string]any)
		entry["go_types"], entry["go_global_types"], entry["go_functions"] = storage.types, rootTypes, allFunctions
	}
	return result, nil
}
func main() {
	fset := token.NewFileSet()
	var result map[string]any
	var err error
	name := os.Args[len(os.Args)-1]
	if name == "--package" {
		result, err = packageInventory(fset)
	} else {
		var file *ast.File
		file, err = parser.ParseFile(fset, name, nil, parser.AllErrors)
		if err == nil {
			result = inventory(file, fset, nil, nil)
		}
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err = json.NewEncoder(os.Stdout).Encode(result); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
