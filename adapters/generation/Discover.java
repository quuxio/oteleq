// Compiler Tree API inventory. Parsing does not initialise application classes.
import com.sun.source.tree.*;
import com.sun.source.util.*;
import javax.tools.*;
import java.util.*;

class Discover {
    static String quote(String value) {
        return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + "\"";
    }
    public static void main(String[] args) throws Exception {
        var compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) throw new IllegalStateException("JDK compiler is required");
        var diagnostics = new DiagnosticCollector<JavaFileObject>();
        try (var manager = compiler.getStandardFileManager(diagnostics, null, null)) {
            var task = (JavacTask) compiler.getTask(null, manager, diagnostics, List.of("-proc:none"), null,
                manager.getJavaFileObjects(args[0]));
            var trees = Trees.instance(task);
            var functions = new ArrayList<String>();
            var globals = new ArrayList<String>();
            var classes = new ArrayDeque<String>();
            String packageName = "";
            for (var unit : task.parse()) {
                packageName = unit.getPackageName()==null ? "" : unit.getPackageName().toString();
                new TreeScanner<Void, Void>() {
                    int methodDepth = 0;
                    public Void visitClass(ClassTree tree, Void unused) {
                        classes.push(tree.getSimpleName().toString());
                        super.visitClass(tree, unused); classes.pop(); return null;
                    }
                    public Void visitMethod(MethodTree tree, Void unused) {
                        var params = tree.getParameters().stream().map(p -> quote(p.getType().toString())).toList();
                        var reason = methodDepth > 0 || classes.size() != 1 ? "nested callable needs an access fixture"
                            : tree.getReturnType() == null ? "constructor needs an object fixture"
                            : !tree.getTypeParameters().isEmpty() || tree.getBody() == null ? "generic or abstract method needs a fixture"
                            : tree.getModifiers().getFlags().contains(javax.lang.model.element.Modifier.PRIVATE) ? "private method needs an access fixture"
                            : !tree.getModifiers().getFlags().contains(javax.lang.model.element.Modifier.STATIC) ? "instance method needs an object fixture" : "";
                        long position = trees.getSourcePositions().getStartPosition(unit, tree);
                        functions.add("{\"name\":" + quote(classes.peek()+"."+tree.getName()) + ",\"line\":" + unit.getLineMap().getLineNumber(position)
                            + ",\"column\":" + unit.getLineMap().getColumnNumber(position)
                            + ",\"parameters\":[" + String.join(",",params) + "],\"output\":" + quote(tree.getReturnType()==null ? "unknown" : tree.getReturnType().toString())
                            + ",\"reason\":" + quote(reason) + "}");
                        methodDepth++; super.visitMethod(tree, unused); methodDepth--; return null;
                    }
                    public Void visitVariable(VariableTree tree, Void unused) {
                        if (methodDepth == 0 && classes.size()==1 && tree.getModifiers().getFlags().contains(javax.lang.model.element.Modifier.STATIC))
                            globals.add("{\"name\":"+quote(classes.peek()+"."+tree.getName())+",\"type\":"+quote(tree.getType().toString())
                                +",\"private\":"+tree.getModifiers().getFlags().contains(javax.lang.model.element.Modifier.PRIVATE)+"}");
                        return super.visitVariable(tree, unused);
                    }
                    public Void visitLambdaExpression(LambdaExpressionTree tree, Void unused) {
                        long position = trees.getSourcePositions().getStartPosition(unit, tree);
                        functions.add("{\"name\":\"<lambda>\",\"line\":"+unit.getLineMap().getLineNumber(position)
                            +",\"column\":"+unit.getLineMap().getColumnNumber(position)+",\"parameters\":[],\"output\":\"unknown\",\"reason\":\"lambda needs a capture fixture\"}");
                        return super.visitLambdaExpression(tree,unused);
                    }
                }.scan(unit, null);
            }
            if (diagnostics.getDiagnostics().stream().anyMatch(d -> d.getKind()==Diagnostic.Kind.ERROR)) throw new IllegalArgumentException("Java parser rejected source");
            System.out.print("{\"functions\":["+String.join(",",functions)+"],\"globals\":["+String.join(",",globals)+"],\"package\":"+quote(packageName)+",\"parser\":\"JDK JavacTask\"}");
        }
    }
}
