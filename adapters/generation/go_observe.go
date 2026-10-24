// Passive observer compiled in a private package, outside application scope.
package oteleqobserver

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"reflect"
	"sort"
	"strconv"
	"strings"
)

type field struct {
	Name     string `json:"name"`
	Type     string `json:"type"`
	Embedded bool   `json:"embedded"`
	Package  string `json:"package"`
	Tag      string `json:"tag_hex"`
}
type model struct {
	Kind    string  `json:"kind"`
	Bits    int     `json:"bits"`
	Signed  bool    `json:"signed"`
	Element string  `json:"element"`
	Length  int     `json:"length"`
	Name    string  `json:"name"`
	Fields  []field `json:"fields"`
}
type input struct {
	Kind  string `json:"kind"`
	Value string `json:"value"`
}
type callInput struct {
	ID        string  `json:"id"`
	Action    string  `json:"action"`
	Arguments []input `json:"arguments"`
}
type configuration struct {
	Models            map[string]model  `json:"models"`
	Roots             map[string]string `json:"roots"`
	Receiver          string            `json:"receiver"`
	MethodReceiver    string            `json:"method_receiver"`
	Parameters        []string          `json:"parameters"`
	FactoryParameters []string          `json:"factory_parameters"`
	Output            string            `json:"output"`
	Arguments         []input           `json:"arguments"`
	FactoryArguments  []input           `json:"factory_arguments"`
	Sequence          []callInput       `json:"sequence,omitempty"`
}

// Root retains the actual address of a package variable, including rebindings.
type Root struct {
	name  string
	value reflect.Value
}

// Bind exposes a declared source variable without formatting its value.
func Bind(name string, value reflect.Value) Root { return Root{name, value} }

func require(ok bool) {
	if !ok {
		panic("Go receiver observation is unavailable")
	}
}

func typeName(kind reflect.Type) string {
	if kind.Name() != "" {
		if kind.PkgPath() != "" {
			return kind.PkgPath() + "." + kind.Name()
		}
		return kind.Name()
	}
	switch kind.Kind() {
	case reflect.Pointer:
		return "*" + typeName(kind.Elem())
	case reflect.Array:
		return "[" + strconv.Itoa(kind.Len()) + "]" + typeName(kind.Elem())
	default:
		return kind.String()
	}
}

func checkType(kind reflect.Type, name string, models map[string]model, seen map[reflect.Type]bool) {
	require(typeName(kind) == name)
	if seen[kind] {
		return
	}
	seen[kind] = true
	storage, ok := models[name]
	require(ok)
	switch storage.Kind {
	case "boolean":
		require(kind.Kind() == reflect.Bool)
	case "string":
		require(kind.Kind() == reflect.String)
	case "integer":
		signed := kind.Kind() >= reflect.Int && kind.Kind() <= reflect.Int64
		unsigned := kind.Kind() >= reflect.Uint && kind.Kind() <= reflect.Uintptr
		require((signed || unsigned) && signed == storage.Signed && kind.Bits() == storage.Bits)
	case "float":
		require((kind.Kind() == reflect.Float32 || kind.Kind() == reflect.Float64) && kind.Bits() == storage.Bits)
	case "pointer":
		require(kind.Kind() == reflect.Pointer)
		checkType(kind.Elem(), storage.Element, models, seen)
	case "array":
		require(kind.Kind() == reflect.Array && kind.Len() == storage.Length)
		checkType(reflect.PointerTo(kind.Elem()), "*"+storage.Element, models, seen)
	case "struct":
		require(kind.Kind() == reflect.Struct && kind.Name() == storage.Name && kind.NumField() == len(storage.Fields))
		for index, expected := range storage.Fields {
			actual := kind.Field(index)
			require(actual.Name == expected.Name && actual.PkgPath == expected.Package && actual.Anonymous == expected.Embedded &&
				hex.EncodeToString([]byte(actual.Tag)) == expected.Tag)
			checkType(reflect.PointerTo(actual.Type), "*"+expected.Type, models, seen)
		}
	default:
		require(false)
	}
}

type value = map[string]any
type node struct {
	ID     string           `json:"id"`
	Type   string           `json:"type"`
	Fields map[string]value `json:"fields"`
}
type snapshot struct {
	Roots map[string]value `json:"roots"`
	Nodes []node           `json:"nodes"`
}
type address struct {
	kind reflect.Type
	data uintptr
}
type graph struct {
	models    map[string]model
	seen      map[address]string
	locations map[uintptr]string
	nodes     []node
	fields    int
	bytes     int
}

// Typed pointer views can share one location, including named-type conversions
// and a struct/array's first field. Keep that relation without exporting addresses.
func (g *graph) location(data uintptr, depth int) value {
	if g.locations == nil {
		g.locations = map[uintptr]string{}
	}
	if prior, exists := g.locations[data]; exists {
		return value{"kind": "reference", "node_id": prior}
	}
	require(depth <= 32 && len(g.nodes) < 512)
	id := "n" + strconv.Itoa(len(g.nodes))
	g.locations[data] = id
	g.nodes = append(g.nodes, node{id, "go.location", map[string]value{}})
	return value{"kind": "reference", "node_id": id}
}

func (g *graph) scalar(item reflect.Value, name string) value {
	if item.Kind() == reflect.String {
		// Charge before hex/JSON allocation; the final JSON limit also includes
		// structural overhead. No collection of individually valid strings may
		// allocate an unbounded intermediate observation.
		g.bytes += 2 * item.Len()
		require(g.bytes <= 262144)
	}
	return primitive(item, name)
}

func primitive(item reflect.Value, name string) value {
	label := "go." + name
	switch item.Kind() {
	case reflect.Bool:
		return value{"kind": "boolean", "type": label, "value": item.Bool()}
	case reflect.String:
		text := item.String()
		require(len(text) <= 65536)
		return value{"kind": "string", "type": label, "encoding": "raw_bytes", "value": hex.EncodeToString([]byte(text))}
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
		return value{"kind": "integer", "type": label, "value": strconv.FormatInt(item.Int(), 10), "bits": item.Type().Bits(), "signed": true}
	case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64, reflect.Uintptr:
		return value{"kind": "integer", "type": label, "value": strconv.FormatUint(item.Uint(), 10), "bits": item.Type().Bits(), "signed": false}
	case reflect.Float32:
		// Widening can quiet a signalling NaN; do not emit an invented payload.
		require(!math.IsNaN(item.Float()))
		return value{"kind": "float", "type": label, "bits": fmt.Sprintf("%08x", math.Float32bits(float32(item.Float())))}
	case reflect.Float64:
		return value{"kind": "float", "type": label, "bits": fmt.Sprintf("%016x", math.Float64bits(item.Float()))}
	default:
		require(false)
		return nil
	}
}

func storageValue(item reflect.Value, pointer bool) (reflect.Value, address) {
	if pointer {
		return item, address{item.Type(), item.Pointer()}
	}
	// Composite returns are values. Materialise their helper-owned copy so field
	// slots can be traversed without inventing aliases to the original storage.
	if !item.CanAddr() {
		clone := reflect.New(item.Type()).Elem()
		clone.Set(item)
		item = clone
	}
	return item, address{item.Type(), item.Addr().Pointer()}
}

func (g *graph) encode(item reflect.Value, expected string, depth int) value {
	require(item.IsValid() && typeName(item.Type()) == expected)
	storage, ok := g.models[expected]
	require(ok)
	if storage.Kind != "pointer" && storage.Kind != "struct" && storage.Kind != "array" {
		return g.scalar(item, expected)
	}
	if storage.Kind == "pointer" && item.IsNil() {
		return value{"kind": "null"}
	}
	item, key := storageValue(item, storage.Kind == "pointer")
	if prior, exists := g.seen[key]; exists {
		return value{"kind": "reference", "node_id": prior}
	}
	require(depth <= 32 && len(g.nodes) < 512)
	id := "n" + strconv.Itoa(len(g.nodes))
	g.seen[key] = id
	contents := map[string]value{}
	g.nodes = append(g.nodes, node{id, "go.storage:" + expected, contents})
	switch storage.Kind {
	case "pointer":
		contents["location"] = g.location(key.data, depth+1)
		contents["value"] = g.encode(item.Elem(), storage.Element, depth+1)
	case "struct":
		for index, field := range storage.Fields {
			contents[field.Name] = g.encode(item.Field(index).Addr(), "*"+field.Type, depth+1)
		}
	case "array":
		for index := 0; index < storage.Length; index++ {
			contents["item:"+strconv.Itoa(index)] = g.encode(item.Index(index).Addr(), "*"+storage.Element, depth+1)
		}
	}
	g.fields += len(contents)
	require(g.fields <= 8192)
	return value{"kind": "reference", "node_id": id}
}

func capture(models map[string]model, roots map[string]reflect.Value, result reflect.Value, output string, outcome bool, failed bool) snapshot {
	g := graph{models: models, seen: map[address]string{}, nodes: []node{}}
	names := []string{}
	for name := range roots {
		names = append(names, name)
	}
	sort.Strings(names)
	values := map[string]value{}
	for _, name := range names {
		values[name] = g.encode(roots[name], typeName(roots[name].Type()), 0)
	}
	if outcome {
		name := "result"
		if failed {
			name = "error"
			// Panic scalars retain their actual type and bits without Error/String.
			values[name] = g.scalar(result, typeName(result.Type()))
		} else if output == "void" {
			values[name] = value{"kind": "undefined"}
		} else {
			values[name] = g.encode(result, output, 0)
		}
	}
	snapshot := snapshot{values, g.nodes}
	encoded, err := json.Marshal(snapshot)
	require(err == nil && len(encoded) <= 262144)
	return snapshot
}

func integerInput(value reflect.Value, text string) {
	kind := value.Kind()
	if kind >= reflect.Int && kind <= reflect.Int64 {
		number, err := strconv.ParseInt(text, 10, 64)
		require(err == nil && !value.OverflowInt(number))
		value.SetInt(number)
	} else {
		require(kind >= reflect.Uint && kind <= reflect.Uintptr)
		number, err := strconv.ParseUint(text, 10, 64)
		require(err == nil && !value.OverflowUint(number))
		value.SetUint(number)
	}
}

func arguments(types []reflect.Type, inputs []input) []reflect.Value {
	require(len(types) == len(inputs))
	result := []reflect.Value{}
	for index, kind := range types {
		item := inputs[index]
		value := reflect.New(kind).Elem()
		switch item.Kind {
		case "integer":
			integerInput(value, item.Value)
		case "float":
			require(kind.Kind() == reflect.Float32 || kind.Kind() == reflect.Float64)
			bits, err := strconv.ParseUint(item.Value, 16, 64)
			number := math.Float64frombits(bits)
			require(err == nil && !math.IsNaN(number) && !math.IsInf(number, 0) && !value.OverflowFloat(number))
			value.SetFloat(number)
		case "boolean":
			require(kind.Kind() == reflect.Bool && (item.Value == "true" || item.Value == "false"))
			value.SetBool(item.Value == "true")
		case "string":
			require(kind.Kind() == reflect.String)
			bytes, err := hex.DecodeString(item.Value)
			require(err == nil && len(bytes) <= 65536)
			value = reflect.ValueOf(bytes).Convert(kind)
		default:
			require(false)
		}
		result = append(result, value)
	}
	return result
}

func signature(function reflect.Value, parameters []string, outputs []string, models map[string]model) []reflect.Type {
	require(function.Kind() == reflect.Func && !function.IsNil())
	kind := function.Type()
	require(!kind.IsVariadic() && kind.NumIn() == len(parameters) && kind.NumOut() == len(outputs))
	inputs := []reflect.Type{}
	seen := map[reflect.Type]bool{}
	for index, name := range parameters {
		checkType(kind.In(index), name, models, seen)
		inputs = append(inputs, kind.In(index))
	}
	for index, name := range outputs {
		checkType(kind.Out(index), name, models, seen)
	}
	return inputs
}

func invoke(target reflect.Value, arguments []reflect.Value) (result reflect.Value, failed bool) {
	returned := false
	defer func() {
		if !returned {
			result, failed = reflect.ValueOf(recover()), true
		}
	}()
	values := target.Call(arguments)
	if len(values) == 1 {
		result = values[0]
	}
	returned = true
	return
}

func declaredRoots(config configuration, globals []Root) map[string]reflect.Value {
	require(config.Roots["receiver"] == config.Receiver)
	require(len(config.Roots) == 1+len(config.Parameters)+len(globals))
	for index, name := range config.Parameters {
		require(config.Roots["argument:"+strconv.Itoa(index)] == name)
	}
	roots := map[string]reflect.Value{}
	for _, root := range globals {
		_, duplicate := roots[root.name]
		require(!duplicate && strings.HasPrefix(root.name, "global:") && len(root.name) > len("global:") && config.Roots[root.name] != "")
		require(root.value.IsValid() && root.value.Kind() == reflect.Pointer && !root.value.IsNil())
		checkType(root.value.Type(), config.Roots[root.name], config.Models, map[reflect.Type]bool{})
		roots[root.name] = root.value
	}
	return roots
}

// Run constructs and calls one source-bound method with fresh scalar inputs.
func Run(encoded string, factory, target reflect.Value, globals ...Root) {
	defer func() {
		if recover() != nil {
			_, _ = os.Stderr.WriteString("Go receiver fixture or observation is unavailable\n")
			os.Exit(91)
		}
	}()
	var config configuration
	require(len(encoded) <= 1048576 && json.Unmarshal([]byte(encoded), &config) == nil)
	require(config.Sequence == nil)
	factoryTypes := signature(factory, config.FactoryParameters, []string{config.Receiver}, config.Models)
	outputs := []string{}
	if config.Output != "void" {
		outputs = append(outputs, config.Output)
	}
	targetTypes := signature(target, append([]string{config.MethodReceiver}, config.Parameters...), outputs, config.Models)
	require(config.MethodReceiver == config.Receiver || config.Receiver == "*"+config.MethodReceiver)
	roots := declaredRoots(config, globals)
	receiver := factory.Call(arguments(factoryTypes, config.FactoryArguments))[0]
	values := arguments(targetTypes[1:], config.Arguments)
	roots["receiver"] = receiver
	for index, argument := range values {
		roots["argument:"+strconv.Itoa(index)] = argument
	}
	require(len(roots) == len(config.Roots))
	before := capture(config.Models, roots, reflect.Value{}, "", false, false)
	actualReceiver := receiver
	if config.MethodReceiver != config.Receiver {
		require(!receiver.IsNil())
		actualReceiver = receiver.Elem()
	}
	result, failed := invoke(target, append([]reflect.Value{actualReceiver}, values...))
	outcome := capture(config.Models, roots, result, config.Output, true, failed)
	after := capture(config.Models, roots, reflect.Value{}, "", false, false)
	kind := "return"
	if failed {
		kind = "error"
	}
	encodedCapture, err := json.Marshal(map[string]any{"go_receiver_schema_version": 2,
		"before": before, "outcome": map[string]any{"kind": kind, "value": outcome}, "after": after})
	require(err == nil && len(encodedCapture) <= 3*262144+1024)
	require(os.WriteFile(os.Getenv("OTELEQ_OBSERVATION"), encodedCapture, 0600) == nil)
}

const maxCapture = 3*262144 + 1024

type callOutcome struct {
	Kind  string   `json:"kind"`
	Value snapshot `json:"value"`
}

type callCapture struct {
	ID      string      `json:"id"`
	Action  string      `json:"action"`
	Before  snapshot    `json:"before"`
	Outcome callOutcome `json:"outcome"`
	After   snapshot    `json:"after"`
}

type captureStream struct {
	file  *os.File
	bytes int
}

func (output *captureStream) write(data []byte) {
	require(len(data) <= maxCapture-output.bytes)
	n, err := output.file.Write(data)
	require(err == nil && n == len(data))
	output.bytes += n
}

func (output *captureStream) value(value any) {
	data, err := json.Marshal(value)
	require(err == nil)
	output.write(data)
}

func receiverCall(config configuration, receiver, target reflect.Value, values []reflect.Value, roots map[string]reflect.Value) callCapture {
	for index, argument := range values {
		roots["argument:"+strconv.Itoa(index)] = argument
	}
	before := capture(config.Models, roots, reflect.Value{}, "", false, false)
	actualReceiver := receiver
	if config.MethodReceiver != config.Receiver {
		require(!receiver.IsNil())
		actualReceiver = receiver.Elem()
	}
	result, failed := invoke(target, append([]reflect.Value{actualReceiver}, values...))
	kind := "return"
	if failed {
		kind = "error"
	}
	return callCapture{Before: before, Outcome: callOutcome{kind, capture(config.Models, roots, result, config.Output, true, failed)},
		After: capture(config.Models, roots, reflect.Value{}, "", false, false)}
}

func runSequence(encoded string, factory, target reflect.Value, globals []Root, checkpoint func(string)) {
	var config configuration
	require(len(encoded) <= 1048576 && json.Unmarshal([]byte(encoded), &config) == nil)
	require(len(config.Sequence) >= 1 && len(config.Sequence) <= 32)
	factoryTypes := signature(factory, config.FactoryParameters, []string{config.Receiver}, config.Models)
	outputs := []string{}
	if config.Output != "void" {
		outputs = append(outputs, config.Output)
	}
	targetTypes := signature(target, append([]string{config.MethodReceiver}, config.Parameters...), outputs, config.Models)
	require(config.MethodReceiver == config.Receiver || config.Receiver == "*"+config.MethodReceiver)
	roots := declaredRoots(config, globals)
	// Validate every concrete call before constructing application state.
	values := make([][]reflect.Value, len(config.Sequence))
	for index, step := range config.Sequence {
		require(step.ID == "step-"+strconv.Itoa(index) && step.Action == "call")
		values[index] = arguments(targetTypes[1:], step.Arguments)
	}
	if checkpoint != nil {
		checkpoint("before-0")
	}
	receiver := factory.Call(arguments(factoryTypes, config.FactoryArguments))[0]
	roots["receiver"] = receiver
	file, err := os.OpenFile(os.Getenv("OTELEQ_OBSERVATION"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	require(err == nil)
	defer file.Close()
	output := captureStream{file: file}
	for index, step := range config.Sequence {
		if checkpoint != nil && index != 0 {
			checkpoint("before-" + strconv.Itoa(index))
		}
		observed := receiverCall(config, receiver, target, values[index], roots)
		observed.ID, observed.Action = step.ID, step.Action
		if index == 0 {
			output.write([]byte(`{"go_receiver_schema_version":3,"before":`))
			output.value(observed.Before)
			output.write([]byte(`,"steps":[`))
		} else {
			output.write([]byte(","))
		}
		output.value(observed)
		if index == len(config.Sequence)-1 {
			output.write([]byte(`],"outcome":`))
			output.value(observed.Outcome)
			output.write([]byte(`,"after":`))
			output.value(observed.After)
		}
		if checkpoint != nil {
			checkpoint("after-" + strconv.Itoa(index))
		}
	}
	output.write([]byte("}\n"))
	require(file.Close() == nil)
	if checkpoint != nil {
		checkpoint("finish")
	}
}

func sequenceFailure() {
	if recover() != nil {
		_, _ = os.Stderr.WriteString("Go receiver fixture or observation is unavailable\n")
		os.Exit(91)
	}
}

// RunSequence retains one constructed receiver and streams each bounded call.
func RunSequence(encoded string, factory, target reflect.Value, globals ...Root) {
	defer sequenceFailure()
	runSequence(encoded, factory, target, globals, nil)
}

// RunControlledSequence pauses the same worker before construction and each call,
// after every call and after the complete capture, before SDK shutdown.
func RunControlledSequence(encoded string, checkpoint func(string), factory, target reflect.Value, globals ...Root) {
	defer sequenceFailure()
	require(checkpoint != nil)
	runSequence(encoded, factory, target, globals, checkpoint)
}
