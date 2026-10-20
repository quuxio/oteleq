// Inventory through the Go parser; never execute the application.
package main

import (
	"bytes"
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
		"entrypoint": node.Recv == nil && node.Name.Name == "main", "name_offset": fset.Position(node.Name.Pos()).Offset}
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
func inventory(file *ast.File, fset *token.FileSet, info *types.Info) map[string]any {
	functions := []any{}
	ast.Inspect(file, func(node ast.Node) bool {
		switch n := node.(type) {
		case *ast.FuncDecl:
			entry := function(n, fset)
			if file.Name.Name != "main" {
				entry["entrypoint"] = false
			}
			if info != nil {
				semanticFunction(entry, n, info)
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
func semanticFunction(entry map[string]any, node *ast.FuncDecl, info *types.Info) {
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
	if signature.Results().Len() == 1 {
		entry["output"] = scalar(signature.Results().At(0).Type())
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
	for _, file := range files {
		for _, root := range globals(file, fset) {
			value := root.(map[string]any)
			value["type"] = scalar(checked.Scope().Lookup(value["name"].(string)).Type())
			roots = append(roots, value)
		}
	}
	result := map[string]any{}
	for index, file := range files {
		entry := inventory(file, fset, info)
		entry["globals"], entry["parser"] = roots, "go/types with selected compiler export data"
		result[request.Files[index]] = entry
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
			result = inventory(file, fset, nil)
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
