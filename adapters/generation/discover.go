// Inventory through the Go parser; never execute the application.
package main

import (
	"bytes"
	"encoding/json"
	"go/ast"
	"go/format"
	"go/parser"
	"go/token"
	"os"
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
	return map[string]any{"name": node.Name.Name, "line": position.Line, "column": position.Column,
		"parameters": parameters(node.Type.Params, fset), "output": output, "reason": reason,
		"entrypoint": node.Recv == nil && node.Name.Name == "main", "name_offset": fset.Position(node.Name.Pos()).Offset}
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
				values = append(values, map[string]any{"name": name.Name, "type": text(value.Type, fset)})
			}
		}
	}
	return values
}
func main() {
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, os.Args[len(os.Args)-1], nil, parser.AllErrors)
	if err != nil {
		panic(err)
	}
	functions := []any{}
	ast.Inspect(file, func(node ast.Node) bool {
		switch n := node.(type) {
		case *ast.FuncDecl:
			functions = append(functions, function(n, fset))
		case *ast.FuncLit:
			position := fset.Position(n.Pos())
			functions = append(functions, map[string]any{"name": "<closure>", "line": position.Line, "column": position.Column,
				"parameters": []string{}, "output": "unknown", "reason": "closure needs a capture fixture"})
		}
		return true
	})
	_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"functions": functions, "globals": globals(file, fset),
		"package": file.Name.Name, "package_end": fset.Position(file.Name.End()).Offset, "parser": "go/parser"})
}
