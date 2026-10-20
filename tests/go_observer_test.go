package oteleqobserver

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

type amount int16
type sample struct {
	count amount `observer:"ignored"`
	next  *sample
	array [2]uint64
}

func schema() (map[string]model, string) {
	name := typeName(reflect.TypeOf(sample{}))
	number := typeName(reflect.TypeOf(amount(0)))
	models := map[string]model{
		name: {Kind: "struct", Name: "sample", Fields: []field{
			{Name: "count", Type: number, Package: "example.test/oteleqobserver", Tag: "6f627365727665723a2269676e6f72656422"},
			{Name: "next", Type: "*" + name, Package: "example.test/oteleqobserver"},
			{Name: "array", Type: "[2]uint64", Package: "example.test/oteleqobserver"}}},
		number:   {Kind: "integer", Bits: 16, Signed: true},
		"uint64": {Kind: "integer", Bits: 64}, "[2]uint64": {Kind: "array", Length: 2, Element: "uint64"},
		"bool": {Kind: "boolean"}, "string": {Kind: "string"}, "float32": {Kind: "float", Bits: 32},
		"float64": {Kind: "float", Bits: 64}, "int64": {Kind: "integer", Bits: 64, Signed: true},
	}
	for _, name := range []string{name, "*" + name, number, "[2]uint64", "uint64"} {
		models["*"+name] = model{Kind: "pointer", Element: name}
	}
	return models, name
}

func refuses(t *testing.T, action func()) {
	t.Helper()
	returned := false
	defer func() {
		if returned || recover() == nil {
			t.Error("unsupported observation was accepted")
		}
	}()
	action()
	returned = true
}

func TestTypesAndStorage(t *testing.T) {
	models, name := schema()
	for _, item := range []any{&sample{}, sample{}, amount(1), uint64(1), [2]uint64{}, true, "text", float32(0), float64(0), int64(0)} {
		kind := reflect.TypeOf(item)
		checkType(kind, typeName(kind), models, map[reflect.Type]bool{})
	}
	s := &sample{count: 7}
	s.next = s
	graph := capture(models, map[string]reflect.Value{"receiver": reflect.ValueOf(s)}, reflect.ValueOf(s), "*"+name, true, false)
	if !reflect.DeepEqual(graph.Roots["receiver"], graph.Roots["result"]) || len(graph.Nodes) != 8 {
		t.Fatalf("lost alias or source slots: %+v", graph)
	}
	capture(models, map[string]reflect.Value{}, reflect.ValueOf(sample{}), name, true, false)
	capture(models, map[string]reflect.Value{"receiver": reflect.ValueOf((*sample)(nil))}, reflect.Value{}, "void", true, false)
	for _, change := range []string{"type", "kind", "tag", "field", "missing"} {
		changed, _ := schema()
		value := changed[name]
		switch change {
		case "type":
			refuses(t, func() { checkType(reflect.TypeOf(s), "unbound", changed, map[reflect.Type]bool{}) })
			continue
		case "kind":
			value.Kind = "opaque"
		case "tag":
			value.Fields[0].Tag = "00"
		case "field":
			value.Fields = value.Fields[:1]
		case "missing":
			delete(changed, name)
			refuses(t, func() { checkType(reflect.TypeOf(s), "*"+name, changed, map[reflect.Type]bool{}) })
			continue
		}
		changed[name] = value
		refuses(t, func() { checkType(reflect.TypeOf(s), "*"+name, changed, map[reflect.Type]bool{}) })
	}
	if typeName(reflect.TypeOf(map[string]int{})) != "map[string]int" {
		t.Fatal("unexpected opaque type label")
	}
}

func TestPrimitiveValuesAndBudgets(t *testing.T) {
	for _, item := range []any{true, "\xff\x00", int8(-2), uint64(math.MaxUint64), float32(-1), math.Float64frombits(0x7ff0000000000001)} {
		value := primitive(reflect.ValueOf(item), typeName(reflect.TypeOf(item)))
		if len(value) < 3 {
			t.Fatal("incomplete primitive", value)
		}
	}
	for _, item := range []any{strings.Repeat("x", 65537), math.Float32frombits(0x7f800001), []int{1}} {
		refuses(t, func() { primitive(reflect.ValueOf(item), typeName(reflect.TypeOf(item))) })
	}
	models, name := schema()
	refuses(t, func() {
		capture(models, map[string]reflect.Value{"x": reflect.Value{}}, reflect.Value{}, "", false, false)
	})
	refuses(t, func() {
		capture(models, map[string]reflect.Value{"x": reflect.ValueOf([]int{})}, reflect.Value{}, "", false, false)
	})
	refuses(t, func() {
		g := graph{models: models, seen: map[address]string{}, nodes: make([]node, 512)}
		g.encode(reflect.ValueOf(&sample{}), "*"+name, 0)
	})
	refuses(t, func() {
		g := graph{models: models, seen: map[address]string{}}
		g.encode(reflect.ValueOf(&sample{}), "*"+name, 33)
	})
	refuses(t, func() {
		g := graph{models: models, seen: map[address]string{}, fields: 8192}
		g.encode(reflect.ValueOf(&sample{}), "*"+name, 0)
	})
	refuses(t, func() {
		g := graph{}
		for i := 0; i < 3; i++ {
			g.scalar(reflect.ValueOf(strings.Repeat("x", 65536)), "string")
		}
	})
	refuses(t, func() {
		roots := map[string]reflect.Value{}
		for i := 0; i < 3; i++ {
			roots[strings.Repeat("r", 65536)+string(rune('a'+i))] = reflect.ValueOf(strings.Repeat("s", 20000))
		}
		capture(models, roots, reflect.Value{}, "", false, false)
	})
}

func TestConcreteInputs(t *testing.T) {
	types := []reflect.Type{reflect.TypeOf(amount(0)), reflect.TypeOf(uint64(0)), reflect.TypeOf(float32(0)), reflect.TypeOf(true), reflect.TypeOf("")}
	values := arguments(types, []input{{"integer", "-3"}, {"integer", "18446744073709551615"}, {"float", "8000000000000000"}, {"boolean", "true"}, {"string", "ff00"}})
	if values[0].Int() != -3 || values[1].Uint() != math.MaxUint64 || !math.Signbit(values[2].Float()) || !values[3].Bool() || values[4].String() != "\xff\x00" {
		t.Fatal("input changed", values)
	}
	for _, pair := range []struct {
		kind reflect.Type
		item input
	}{
		{types[0], input{"integer", "65536"}}, {types[1], input{"integer", "-1"}},
		{types[2], input{"float", "7ff0000000000000"}}, {types[2], input{"float", "x"}},
		{types[3], input{"boolean", "other"}}, {types[4], input{"string", "x"}},
		{types[0], input{"opaque", "x"}}, {types[4], input{"integer", "1"}},
		{types[0], input{"float", "0000000000000000"}}, {types[0], input{"string", "00"}},
	} {
		refuses(t, func() { arguments([]reflect.Type{pair.kind}, []input{pair.item}) })
	}
	refuses(t, func() { arguments(types, nil) })
}

func TestCallsAndDeclarations(t *testing.T) {
	models, name := schema()
	factory := reflect.ValueOf(func(seed amount) *sample { return &sample{count: seed} })
	method := reflect.ValueOf(func(s *sample, delta amount) amount { s.count += delta; return s.count })
	parameters := signature(factory, []string{typeName(reflect.TypeOf(amount(0)))}, []string{"*" + name}, models)
	if len(parameters) != 1 {
		t.Fatal("missing signature")
	}
	for _, target := range []any{7, (func())(nil), func(...int64) {}, func() {}} {
		refuses(t, func() { signature(reflect.ValueOf(target), []string{"int64"}, nil, models) })
	}
	result, failed := invoke(reflect.ValueOf(func() string { panic("known") }), nil)
	if !failed || result.String() != "known" {
		t.Fatal("lost panic")
	}
	capture(models, map[string]reflect.Value{}, result, "", true, true)
	_, failed = invoke(reflect.ValueOf(func() {}), nil)
	if failed {
		t.Fatal("void call failed")
	}
	number := typeName(reflect.TypeOf(amount(0)))
	config := configuration{Models: models, Receiver: "*" + name, MethodReceiver: "*" + name,
		Parameters: []string{number}, FactoryParameters: []string{number}, Output: number,
		Arguments: []input{{"integer", "3"}}, FactoryArguments: []input{{"integer", "10"}},
		Roots: map[string]string{"receiver": "*" + name, "argument:0": number, "global:total": "*" + number}}
	var total amount
	global := Bind("global:total", reflect.ValueOf(&total))
	declaredRoots(config, []Root{global})
	refuses(t, func() { declaredRoots(config, nil) })
	refuses(t, func() { declaredRoots(config, []Root{Bind("receiver", reflect.ValueOf(&total))}) })
	refuses(t, func() { declaredRoots(config, []Root{Bind("global:total", reflect.ValueOf((*amount)(nil)))}) })
	config.Roots["receiver"] = number
	refuses(t, func() { declaredRoots(config, []Root{global}) })
	config.Roots["receiver"] = "*" + name
	config.Roots["argument:0"] = "string"
	refuses(t, func() { declaredRoots(config, []Root{global}) })
	config.Roots["argument:0"] = number
	encoded, err := json.Marshal(config)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "observation.json")
	t.Setenv("OTELEQ_OBSERVATION", path)
	Run(string(encoded), factory, method, global)
	data, err := os.ReadFile(path)
	if err != nil || !json.Valid(data) || !strings.Contains(string(data), `"value":"13"`) {
		t.Fatal("missing complete capture", err, string(data))
	}
}
