"""Generate compiler-checked passive access in the private C++ translation unit."""
import json

import cpp_receivers
import cpp_models
import native_names


NEXT_DEPTH = "depth+1"


def quoted(value: str) -> str:
    """A C++ string literal containing a complete quoted JSON string."""
    return json.dumps(json.dumps(value, ensure_ascii=True))


class Worker:
    """Each frozen type has one checked writer; fields retain their own slots."""

    def __init__(self, entry: dict, arguments: list, literal) -> None:
        self.entry = entry
        self.contract = entry["cpp_receiver"]
        self.models = self.contract["types"]
        self.ids = {name: index for index, name in enumerate(sorted(self.models))}
        self.arguments = arguments
        self.literal = literal

    def type_name(self, name: str) -> str:
        """Source records always resolve globally, never to an observer helper."""
        if name == "void" or name in cpp_models.BUILTINS:
            return name
        model = self.models[name]
        kind = model["kind"]
        if kind == "record":
            return "::" + name
        if kind == "qualified":
            return "const " + self.type_name(model["element"])
        if kind in ("pointer", "reference"):
            return self.type_name(model["element"]) + (" *" if kind == "pointer" else " &")
        dimensions = cpp_models.ARRAY.fullmatch(name)
        return self.type_name(dimensions[1]) + "[" + dimensions[2] + "]" + dimensions[3]

    def view(self, name: str, address: str, depth: str = "0") -> str:
        """Register a view without dereferencing it or calling an overloaded address."""
        return ("g.reference(" + str(self.ids[name]) + "," + quoted("cpp.storage:" + name)
                + "," + address + ",write_" + str(self.ids[name]) + "," + depth + ");")

    def field(self, name: str, type_: str, address: str) -> str:
        """The declared field name and compiler-resolved type are separate bindings."""
        return "g.field(" + quoted(name) + ");" + self.view(type_, address, NEXT_DEPTH)

    def access(self, name: str, record: dict) -> str:
        """Friend access permits private data and exact method overload selection."""
        fields = []
        for field in record["fields"] if name in self.models else []:
            type_ = field["canonical"]
            fields.append("static_assert(std::is_same_v<decltype(value->" + field["name"] + "),type_"
                          + str(self.ids[type_]) + ">,\"source field type differs\");")
            fields.append(self.field("field:" + field["name"], type_, "__builtin_addressof(value->" + field["name"] + ")"))
        statics = []
        for index, item in enumerate(self.contract["globals"]):
            if item["owner"] == name:
                leaf = item["name"].rsplit("::", 1)[-1]
                statics.append("static auto global_" + str(index) + "(){return __builtin_addressof(::" + name + "::" + leaf + ");}")
        factory = ""
        if name == self.contract["owner"]:
            method = self.contract["method"]
            method_type = self.type_name(method["output"]) + " (::" + name + "::*)(" + ",".join(self.type_name(item) for item in method["parameters"]) + ") " + method["qualifiers"]
            factory = ("using target_type=" + method_type + ";\nstatic target_type target(){return static_cast<target_type>(&::"
                       + method["name"] + ");}\nstatic int run();\n")
        return ("template<> struct access<::" + name + ">{\nstatic void fields(Graph& g,const ::" + name
                + "* value,unsigned depth){" + "\n".join(fields) + "}\n" + "\n".join(statics) + factory + "};\n")

    def writer(self, name: str, model: dict) -> str:
        """Only declared primitive bytes, pointer views, arrays and source fields."""
        index, kind = self.ids[name], model["kind"]
        body = 'g.field("\\\"location\\\"");g.location(address,depth+1);'
        if kind in ("integer", "float", "boolean"):
            body += 'g.field("\\\"value\\\"");g.scalar(' + quoted(name) + ',address,sizeof(type_' + str(index) + '));'
        elif kind == "record":
            body += "access<type_" + str(index) + ">::fields(g,value,depth);"
        elif kind == "array":
            body += ("for(std::size_t i=0;i<" + str(model["length"]) + ";++i){g.item(i);"
                     + self.view(model["element"], "__builtin_addressof((*value)[i])", NEXT_DEPTH) + "}")
        else:
            body += 'g.field("\\\"value\\\"");'
            if kind == "pointer":
                body += "if(*value==nullptr)g.absent();else{" + self.view(model["element"], "*value", NEXT_DEPTH) + "}"
            else:
                body += self.view(model["element"], "address", NEXT_DEPTH)
        return ("static void write_" + str(index) + "(Graph& g,const void* address,unsigned depth){\n"
                + "auto value=static_cast<const std::remove_reference_t<type_" + str(index) + ">*>(address);\n"
                + body + "\n}\n")

    def roots(self) -> str:
        """Every boundary contains the same required receiver, input and global slots."""
        roots = [("receiver", self.contract["owner"], "__builtin_addressof(receiver)")]
        roots.extend(("argument:" + str(index), type_, "__builtin_addressof(argument_" + str(index) + ")")
                     for index, type_ in enumerate(self.contract["method"]["parameters"]))
        for index, item in enumerate(self.contract["globals"]):
            address = ("access<::" + item["owner"] + ">::global_" + str(index) + "()" if item["owner"]
                       else "__builtin_addressof(::" + item["name"] + ")")
            roots.append(("global:" + item["name"], item["type"], address))
        return "\n".join("g.field(" + quoted(name) + ");" + self.view(type_, address) for name, type_, address in roots)

    def source(self) -> str:
        """Construct independently and retain the returned value through all boundaries."""
        aliases = "\n".join("using type_" + str(index) + "=" + self.type_name(name) + ";" for name, index in self.ids.items())
        forwards = "\n".join("static void write_" + str(index) + "(Graph&,const void*,unsigned);" for index in self.ids.values())
        access = "\n".join(self.access(name, record) for name, record in self.contract["records"].items())
        writers = "\n".join(self.writer(name, model) for name, model in self.models.items())
        owner, method = self.contract["owner"], self.contract["method"]
        arguments = "\n".join(self.type_name(type_) + " argument_" + str(index) + "=" + self.literal(value, type_, "cpp") + ";"
                              for index, (type_, value) in enumerate(zip(method["parameters"], self.arguments)))
        target = "static_cast<::" + owner + "&&>(receiver)" if "&&" in method["qualifiers"].split() else "receiver"
        call = "(" + target + ".*access<::" + owner + ">::target())(" + ",".join("argument_" + str(i) for i in range(len(self.arguments))) + ")"
        invocation = call + ";" if method["output"] == "void" else "decltype(auto) result=" + call + ";"
        result = "g.unit();" if method["output"] == "void" else self.view(method["output"], "__builtin_addressof(result)")
        # Save roots before adding the result so the field delimiter state is local.
        roots = self.roots()
        invocation = ("try{" + invocation + "Graph& g=outcome;g.begin();" + roots + 'g.field("\\\"result\\\"");' + result
                      + "g.finish();{Graph& g=after;g.begin();" + roots + "g.finish();}}"
                      + "catch(const std::exception& error){error_outcome=true;Graph& g=outcome;g.begin();" + roots
                      + 'g.field("\\\"error\\\"");g.error(error);g.finish();{Graph& g=after;g.begin();' + roots + "g.finish();}}")
        fixture = self.contract["factory"]
        inputs = ",".join(self.literal(value, type_, "cpp") for value, type_ in zip(fixture["arguments"], fixture["parameters"]))
        # Construct inside the friend. Returning a small trivial source object
        # through another helper can introduce ABI copies and dangling self pointers.
        creation = self.type_name(owner) + " receiver=::" + fixture["name"] + "(" + inputs + ");"
        main = ("int access<::" + owner + ">::run(){Graph before,outcome,after;bool error_outcome=false;" + creation
                + arguments + "{Graph& g=before;g.begin();" + roots + "g.finish();}" + invocation + r'''
std::FILE* output=std::fopen(std::getenv("OTELEQ_OBSERVATION"),"wb");if(!output)return 90;
__oteleq_abi(output);
bool ok=std::fputs("{\"cpp_receiver_schema_version\":1,\"before\":",output)>=0 && before.write(output)
 && std::fputs(error_outcome?",\"outcome\":{\"kind\":\"error\",\"value\":":",\"outcome\":{\"kind\":\"return\",\"value\":",output)>=0
 && outcome.write(output) && std::fputs("},\"after\":",output)>=0 && after.write(output) && std::fputs("}\n",output)>=0;
return std::fclose(output)==0 && ok?0:92;}
''')
        generated = "namespace __oteleq_cpp {\n" + aliases + forwards + access + writers + main + "}\n"
        clean = cpp_receivers.sanitise_identifiers(self.contract) + native_names.undefinitions(generated)
        return clean + generated + '\nint main(){try{return __oteleq_cpp::access<::' + owner + '>::run();}\n' + '''
catch(const __oteleq_cpp::capture_failure& error){std::fprintf(stderr,"C++ observation incomplete: %s\\n",error.reason);return 91;}
catch(...){std::fputs("C++ fixture or exception needs another codec\\n",stderr);return 91;}}
'''
