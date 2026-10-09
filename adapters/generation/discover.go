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
func main() {
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, os.Args[len(os.Args)-1], nil, parser.AllErrors)
	if err != nil {
		panic(err)
	}
	functions := []any{}
	globals := []any{}
	ast.Inspect(file, func(node ast.Node) bool {
		switch n := node.(type) {
		case *ast.FuncDecl:
			params := []string{}
			for _, field := range n.Type.Params.List {
				count := len(field.Names)
				if count == 0 {
					count = 1
				}
				for i := 0; i < count; i++ {
					params = append(params, text(field.Type, fset))
				}
			}
			output := "void"
			reason := ""
			if n.Type.Results != nil {
				if len(n.Type.Results.List) == 1 && len(n.Type.Results.List[0].Names) <= 1 {
					output = text(n.Type.Results.List[0].Type, fset)
				} else {
					reason = "multiple results need a result fixture"
				}
			}
			if n.Recv != nil || n.Type.TypeParams != nil {
				reason = "method or generic callable needs a fixture"
			}
			if n.Body == nil {
				reason = "external declaration needs a build recipe"
			}
			functions = append(functions, map[string]any{"name": n.Name.Name, "line": fset.Position(n.Pos()).Line, "column": fset.Position(n.Pos()).Column,
				"parameters": params, "output": output, "reason": reason, "name_offset": fset.Position(n.Name.Pos()).Offset})
		case *ast.FuncLit:
			functions = append(functions, map[string]any{"name": "<closure>", "line": fset.Position(n.Pos()).Line, "column": fset.Position(n.Pos()).Column,
				"parameters": []string{}, "output": "unknown", "reason": "closure needs a capture fixture"})
		}
		return true
	})
	for _, decl := range file.Decls {
		if group, ok := decl.(*ast.GenDecl); ok && group.Tok == token.VAR {
			for _, spec := range group.Specs {
				value := spec.(*ast.ValueSpec)
				for _, name := range value.Names {
					globals = append(globals, map[string]any{"name": name.Name, "type": text(value.Type, fset)})
				}
			}
		}
	}
	_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"functions": functions, "globals": globals,
		"package": file.Name.Name, "package_end": fset.Position(file.Name.End()).Offset, "parser": "go/parser"})
}
