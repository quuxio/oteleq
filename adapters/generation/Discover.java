// Compiler Tree API inventory. Parsing does not initialise application classes.
import com.sun.source.tree.ClassTree;
import com.sun.source.tree.LambdaExpressionTree;
import com.sun.source.tree.MethodTree;
import com.sun.source.tree.Tree;
import com.sun.source.tree.VariableTree;
import com.sun.source.util.JavacTask;
import com.sun.source.util.TreeScanner;
import com.sun.source.util.Trees;
import java.lang.Exception;
import java.lang.IllegalArgumentException;
import java.lang.IllegalStateException;
import java.lang.String;
import java.lang.System;
import java.lang.Void;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import javax.tools.Diagnostic;
import javax.tools.DiagnosticCollector;
import javax.tools.JavaFileObject;
import javax.tools.ToolProvider;

class Discover {
    static String quote(String value) {
        return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + "\"";
    }
    static int modifiers(Set<javax.lang.model.element.Modifier> flags) {
        int result = 0;
        for (var flag : flags) result |= switch (flag) {
            case PUBLIC -> 1;
            case PRIVATE -> 2;
            case PROTECTED -> 4;
            case STATIC -> 8;
            case FINAL -> 16;
            case VOLATILE -> 64;
            case TRANSIENT -> 128;
            default -> 0;
        };
        return result;
    }
    static String receiverReason(ClassTree tree) {
        if (tree.getKind() != Tree.Kind.CLASS || !tree.getTypeParameters().isEmpty()
                || tree.getModifiers().getFlags().contains(javax.lang.model.element.Modifier.ABSTRACT))
            return "receiver requires an ordinary concrete source class";
        if (!tree.getImplementsClause().isEmpty() || tree.getExtendsClause() != null
                && !Set.of("Object", "java.lang.Object").contains(tree.getExtendsClause().toString()))
            return "inherited receiver storage requires another fixture";
        if (tree.getMembers().stream().anyMatch(member -> member instanceof MethodTree method
                && method.getModifiers().getFlags().contains(javax.lang.model.element.Modifier.NATIVE)))
            return "native receiver methods require another fixture";
        return "";
    }
    static String classRecord(ClassTree tree) {
        var fields = new ArrayList<String>();
        for (var member : tree.getMembers()) {
            if (member instanceof VariableTree field) fields.add("{\"name\":" + quote(field.getName().toString())
                + ",\"type\":" + quote(field.getType().toString()) + ",\"modifiers\":" + modifiers(field.getModifiers().getFlags()) + "}");
        }
        return "{\"name\":" + quote(tree.getSimpleName().toString()) + ",\"reason\":" + quote(receiverReason(tree))
            + ",\"fields\":[" + String.join(",", fields) + "]}";
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
            var classRecords = new ArrayList<String>();
            var classes = new ArrayDeque<String>();
            var classTrees = new ArrayDeque<ClassTree>();
            String packageName = "";
            for (var unit : task.parse()) {
                packageName = unit.getPackageName()==null ? "" : unit.getPackageName().toString();
                new TreeScanner<Void, Void>() {
                    int methodDepth = 0;
                    public Void visitClass(ClassTree tree, Void unused) {
                        if (classes.isEmpty() && methodDepth == 0) classRecords.add(classRecord(tree));
                        classes.push(tree.getSimpleName().toString());
                        classTrees.push(tree);
                        super.visitClass(tree, unused); classes.pop(); classTrees.pop(); return null;
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
                            + ",\"reason\":" + quote(reason)
                            + ",\"java_receiver_class\":" + quote(classes.peek())
                            + ",\"java_static\":" + tree.getModifiers().getFlags().contains(javax.lang.model.element.Modifier.STATIC)
                            + ",\"java_private\":" + tree.getModifiers().getFlags().contains(javax.lang.model.element.Modifier.PRIVATE)
                            + ",\"java_constructor\":" + (tree.getReturnType() == null)
                            + ",\"java_receiver_reason\":" + quote(methodDepth > 0 || classes.size() != 1 ? "nested receiver requires another fixture" : receiverReason(classTrees.peek()))
                            + "}");
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
            System.out.print("{\"functions\":["+String.join(",",functions)+"],\"globals\":["+String.join(",",globals)
                +"],\"classes\":["+String.join(",",classRecords)+"],\"package\":"+quote(packageName)+",\"parser\":\"JDK JavacTask\"}");
        }
    }
}
