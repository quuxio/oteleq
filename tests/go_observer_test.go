package oteleqobserver

import (
	"encoding/json"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strconv"
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
	if !reflect.DeepEqual(graph.Roots["receiver"], graph.Roots["result"]) || len(graph.Nodes) != 12 {
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

func sequenceConfig() (configuration, string, string) {
	models, name := schema()
	number := typeName(reflect.TypeOf(amount(0)))
	return configuration{Models: models, Receiver: "*" + name, MethodReceiver: "*" + name,
		Parameters: []string{number}, FactoryParameters: []string{number}, Output: number,
		FactoryArguments: []input{{"integer", "10"}},
		Roots:            map[string]string{"receiver": "*" + name, "argument:0": number, "global:total": "*" + number}}, name, number
}

func sequenceValues(values ...string) []callInput {
	result := []callInput{}
	for index, value := range values {
		result = append(result, callInput{ID: "step-" + strconv.Itoa(index), Action: "call", Arguments: []input{{"integer", value}}})
	}
	return result
}

func capturedNumber(t *testing.T, graph snapshot, root string, fields ...string) string {
	t.Helper()
	value := graph.Roots[root]
	for _, field := range fields {
		if value == nil {
			t.Fatal("missing literal reference", root, field, value)
		}
		found := false
		for _, node := range graph.Nodes {
			if node.ID == value["node_id"] {
				value, found = node.Fields[field], true
				break
			}
		}
		if !found {
			t.Fatal("missing literal field", root, field)
		}
	}
	return value["value"].(string)
}

func TestSequenceRetainsIntermediateMutationAndContinuesAfterPanic(t *testing.T) {
	config, _, _ := sequenceConfig()
	config.Sequence = sequenceValues("3", "-2", "4")
	constructions := 0
	var total amount
	factory := reflect.ValueOf(func(seed amount) *sample { constructions++; return &sample{count: seed} })
	target := reflect.ValueOf(func(receiver *sample, value amount) amount {
		receiver.count += value
		total += value
		if value < 0 {
			panic("known")
		}
		return receiver.count
	})
	encoded, err := json.Marshal(config)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "sequence.json")
	t.Setenv("OTELEQ_OBSERVATION", path)
	RunSequence(string(encoded), factory, target, Bind("global:total", reflect.ValueOf(&total)))
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var capture struct {
		Version int           `json:"go_receiver_schema_version"`
		Before  snapshot      `json:"before"`
		Steps   []callCapture `json:"steps"`
		Outcome callOutcome   `json:"outcome"`
		After   snapshot      `json:"after"`
	}
	if json.Unmarshal(data, &capture) != nil || capture.Version != 3 || len(capture.Steps) != 3 || constructions != 1 || total != 5 {
		t.Fatal("incomplete sequence", constructions, total, string(data))
	}
	for index, expected := range []struct{ before, after, global, outcome string }{{"10", "13", "3", "return"}, {"13", "11", "1", "error"}, {"11", "15", "5", "return"}} {
		step := capture.Steps[index]
		if step.ID != "step-"+strconv.Itoa(index) || step.Action != "call" || step.Outcome.Kind != expected.outcome ||
			capturedNumber(t, step.Before, "receiver", "value", "count", "value") != expected.before ||
			capturedNumber(t, step.After, "receiver", "value", "count", "value") != expected.after ||
			capturedNumber(t, step.After, "global:total", "value") != expected.global {
			t.Fatal("wrong intermediate value", index, step)
		}
	}
	if !reflect.DeepEqual(capture.Before, capture.Steps[0].Before) || !reflect.DeepEqual(capture.After, capture.Steps[2].After) ||
		!reflect.DeepEqual(capture.Outcome, capture.Steps[2].Outcome) {
		t.Fatal("outer summary differs")
	}
}

func TestSequenceBoundsValueCopiesAndValidationBeforeConstruction(t *testing.T) {
	config, name, _ := sequenceConfig()
	config.MethodReceiver = name
	var total amount
	constructions := 0
	factory := reflect.ValueOf(func(seed amount) *sample { constructions++; return &sample{count: seed} })
	target := reflect.ValueOf(func(receiver sample, value amount) amount {
		receiver.count += value
		total += value
		return receiver.count
	})
	for _, count := range []int{1, 32} {
		values := make([]string, count)
		for index := range values {
			values[index] = "3"
		}
		config.Sequence = sequenceValues(values...)
		encoded, _ := json.Marshal(config)
		path := filepath.Join(t.TempDir(), "sequence.json")
		t.Setenv("OTELEQ_OBSERVATION", path)
		runSequence(string(encoded), factory, target, []Root{Bind("global:total", reflect.ValueOf(&total))}, nil)
		data, err := os.ReadFile(path)
		if err != nil || !json.Valid(data) || !strings.Contains(string(data), `"value":"13"`) {
			t.Fatal("value sequence failed", err)
		}
	}
	if constructions != 2 || total != 99 {
		t.Fatal("receiver was reconstructed or value calls lost", constructions, total)
	}
	for _, change := range []string{"empty", "many", "id", "action", "arguments", "signature", "nil-value", "path"} {
		config.Sequence = sequenceValues("3")
		switch change {
		case "empty":
			config.Sequence = nil
		case "many":
			config.Sequence = make([]callInput, 33)
		case "id":
			config.Sequence[0].ID = "other"
		case "action":
			config.Sequence[0].Action = "release"
		case "arguments":
			config.Sequence[0].Arguments = nil
		}
		encoded, _ := json.Marshal(config)
		calls := constructions
		selected := target
		creator := factory
		if change == "signature" {
			selected = reflect.ValueOf(func() {})
		}
		if change == "nil-value" {
			creator = reflect.ValueOf(func(amount) *sample { return nil })
		}
		path := filepath.Join(t.TempDir(), "sequence.json")
		if change == "path" {
			if err := os.WriteFile(path, nil, 0600); err != nil {
				t.Fatal(err)
			}
		}
		t.Setenv("OTELEQ_OBSERVATION", path)
		refuses(t, func() {
			runSequence(string(encoded), creator, selected, []Root{Bind("global:total", reflect.ValueOf(&total))}, nil)
		})
		if change != "nil-value" && change != "path" && constructions != calls {
			t.Fatal("invalid schedule constructed application state", change)
		}
	}
	refuses(t, func() { runSequence("not json", factory, target, nil, nil) })
}

func TestSequenceVoidAndBoundedOutputFailures(t *testing.T) {
	config, _, _ := sequenceConfig()
	config.Sequence = sequenceValues("3")
	config.Output = "void"
	var total amount
	factory := reflect.ValueOf(func(seed amount) *sample { return &sample{count: seed} })
	target := reflect.ValueOf(func(receiver *sample, value amount) { receiver.count += value; total += value })
	encoded, _ := json.Marshal(config)
	path := filepath.Join(t.TempDir(), "void.json")
	t.Setenv("OTELEQ_OBSERVATION", path)
	runSequence(string(encoded), factory, target, []Root{Bind("global:total", reflect.ValueOf(&total))}, nil)
	data, err := os.ReadFile(path)
	if err != nil || !strings.Contains(string(data), `"kind":"undefined"`) {
		t.Fatal("missing void outcome", err, string(data))
	}
	file, err := os.CreateTemp(t.TempDir(), "bounded")
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	output := captureStream{file: file, bytes: maxCapture}
	refuses(t, func() { output.write([]byte("x")) })
	output.bytes = 0
	refuses(t, func() { output.value(make(chan int)) })
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	refuses(t, func() { output.write([]byte("x")) })
}

func TestControlledCallsPauseBeforeConstructionAndFinishAfterCompleteCapture(t *testing.T) {
	config, _, _ := sequenceConfig()
	config.Sequence = sequenceValues("3", "-2", "4")
	var total amount
	constructions, calls := 0, 0
	factory := reflect.ValueOf(func(seed amount) *sample { constructions++; return &sample{count: seed} })
	target := reflect.ValueOf(func(receiver *sample, value amount) amount {
		calls++
		total += value
		receiver.count += value
		if value < 0 {
			panic("known")
		}
		return receiver.count
	})
	encoded, _ := json.Marshal(config)
	path := filepath.Join(t.TempDir(), "controlled.json")
	t.Setenv("OTELEQ_OBSERVATION", path)
	var phases []string
	checkpoint := func(phase string) {
		phases = append(phases, phase)
		if phase == "before-0" && (constructions != 0 || calls != 0 || total != 0) {
			t.Fatal("application ran before the initial checkpoint")
		}
		if phase == "after-0" && (constructions != 1 || calls != 1 || total != 3) {
			t.Fatal("factory or first call missing at checkpoint")
		}
		if phase == "before-1" && (calls != 1 || total != 3) || phase == "after-1" && (calls != 2 || total != 1) {
			t.Fatal("panic boundary differs")
		}
		if phase == "finish" {
			data, err := os.ReadFile(path)
			if err != nil || !json.Valid(data) || constructions != 1 || calls != 3 || total != 5 {
				t.Fatal("finish precedes a complete retained sequence", err)
			}
		}
	}
	RunControlledSequence(string(encoded), checkpoint, factory, target, Bind("global:total", reflect.ValueOf(&total)))
	if !reflect.DeepEqual(phases, []string{"before-0", "after-0", "before-1", "after-1", "before-2", "after-2", "finish"}) {
		t.Fatal("missing or reordered host checkpoints", phases)
	}
}

func TestControlledSequenceRefusesMissingHostBeforeFactory(t *testing.T) {
	if os.Getenv("OTELEQ_TEST_MISSING_GO_HOST") == "1" {
		config, _, _ := sequenceConfig()
		config.Sequence = sequenceValues("3")
		encoded, _ := json.Marshal(config)
		var total amount
		factory := reflect.ValueOf(func(seed amount) *sample {
			_, _ = os.Stdout.WriteString("APPLICATION_FACTORY_RAN\n")
			return &sample{count: seed}
		})
		target := reflect.ValueOf(func(receiver *sample, value amount) amount { return receiver.count + value })
		RunControlledSequence(string(encoded), nil, factory, target, Bind("global:total", reflect.ValueOf(&total)))
		return
	}
	path := filepath.Join(t.TempDir(), "must-not-exist.json")
	command := exec.Command(os.Args[0], "-test.run=^TestControlledSequenceRefusesMissingHostBeforeFactory$")
	command.Env = append(os.Environ(), "OTELEQ_TEST_MISSING_GO_HOST=1", "OTELEQ_OBSERVATION="+path)
	output, err := command.Output()
	failure, ok := err.(*exec.ExitError)
	if !ok || failure.ExitCode() != 91 || len(output) != 0 || string(failure.Stderr) != "Go receiver fixture or observation is unavailable\n" {
		t.Fatal("missing host was accepted or application code ran", err, string(output))
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("missing host created an observation")
	}
}
