// Syntax inventory only: no application module is loaded.
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.argv[2] + '/adapters/node/package.json');
const ts = require('typescript');
// Source arrives on the dedicated bounded worker input, not an arbitrary CLI filesystem path.
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = ts.createSourceFile(input.filename, input.source, ts.ScriptTarget.Latest, true);
if (source.parseDiagnostics.length) throw new Error('TypeScript parser rejected source');
const functions = [], globals = [];
// Preserve the hashbang and directive prologue before inserting a hoisted
// declaration binding capture. UTF-16 parser offsets become UTF-8 byte offsets.
let bindingCaptureOffset = source.statements[0]?.getStart(source) ?? input.source.length;
for (const statement of source.statements) {
  if (!ts.isExpressionStatement(statement) || !ts.isStringLiteral(statement.expression)) break;
  bindingCaptureOffset = statement.end;
}
function modifier(node,kind) { return node.modifiers?.some(item=>item.kind===kind) ?? false; }
function decorated(node) { return ts.canHaveDecorators(node) && Boolean(ts.getDecorators(node)?.length); }
function nodeName(node) {
  if(ts.isConstructorDeclaration(node)) return 'constructor';
  if(node.name && (ts.isIdentifier(node.name)||ts.isPrivateIdentifier(node.name)||ts.isStringLiteral(node.name)||ts.isNumericLiteral(node.name))) return node.name.text;
  const parent=node.parent;
  if(parent && (ts.isVariableDeclaration(parent)||ts.isPropertyDeclaration(parent)||ts.isPropertyAssignment(parent)) && ts.isIdentifier(parent.name)) return parent.name.text;
  return node.name?.getText(source) ?? '<anonymous>';
}
function callableReason(node) {
  if(node.typeParameters?.length || node.parameters.some(p => p.dotDotDotToken)) return 'generic or variadic callable needs a fixture';
  if(node.parameters.some(p=>!ts.isIdentifier(p.name)||p.name.text==='this')) return 'destructured or explicit-this parameters need a fixture';
  if(node.asteriskToken) return 'generator callable needs an iteration fixture';
  if(decorated(node)) return 'decorated callable needs a fixture';
  if(!node.body) return 'declaration has no source body';
  return '';
}
function classMemberReason(member) {
  if(member.name && !ts.isIdentifier(member.name)) return 'computed, literal or private class members require a fixture';
  if(decorated(member)||modifier(member,ts.SyntaxKind.AccessorKeyword)||ts.isGetAccessorDeclaration(member)||ts.isSetAccessorDeclaration(member)) return 'class accessors or decorators require a fixture';
  if(modifier(member,ts.SyntaxKind.PrivateKeyword)||modifier(member,ts.SyntaxKind.ProtectedKeyword)) return 'non-public class members require a fixture';
  if(member.parameters?.some(p=>modifier(p,ts.SyntaxKind.PrivateKeyword)||modifier(p,ts.SyntaxKind.ProtectedKeyword))) return 'private constructor storage requires a fixture';
  return '';
}
function foreignConstructorReturn(node) {
  if(ts.isReturnStatement(node)) return Boolean(node.expression&&node.expression.kind!==ts.SyntaxKind.ThisKeyword);
  if(ts.isFunctionLike(node)||ts.isClassLike(node)) return false;
  return ts.forEachChild(node,foreignConstructorReturn)??false;
}
function classReason(node) {
  if(!ts.isClassDeclaration(node)||!node.name||!ts.isSourceFile(node.parent)) return 'receiver class requires a named top-level declaration';
  if(node.heritageClauses?.length||node.typeParameters?.length||decorated(node)||modifier(node,ts.SyntaxKind.AbstractKeyword)) return 'inherited, generic, abstract or decorated class requires a fixture';
  for(const member of node.members) {
    const reason=classMemberReason(member);
    if(reason) return reason;
    if(ts.isConstructorDeclaration(member)&&member.body&&foreignConstructorReturn(member.body)) return 'constructor return overrides require an allocation fixture';
  }
  const methods=node.members.filter(member=>ts.isMethodDeclaration(member)&&!modifier(member,ts.SyntaxKind.StaticKeyword)).map(nodeName);
  if(new Set(methods).size!==methods.length) return 'duplicate class method bindings require a fixture';
  const statics=node.members.filter(member=>ts.isPropertyDeclaration(member)&&modifier(member,ts.SyntaxKind.StaticKeyword)).map(nodeName);
  if(new Set(statics).size!==statics.length) return 'duplicate static field declarations require a fixture';
  return '';
}
function classInfo(node) {
  return {name:node.name?.text??'<class>',reason:classReason(node),
    capture:Buffer.byteLength(input.source.slice(0,node.members.pos),'utf8'),
    methods:node.members.filter(member=>ts.isMethodDeclaration(member)&&!modifier(member,ts.SyntaxKind.StaticKeyword)).map(nodeName),
    statics:node.members.filter(member=>ts.isPropertyDeclaration(member)&&modifier(member,ts.SyntaxKind.StaticKeyword)).map(member=>({name:nodeName(member),type:member.type?.getText(source)??'dynamic'}))};
}
function receiverMetadata(node,owner,reason) {
  if(!owner) return {};
  if(ts.isConstructorDeclaration(node)) return !owner.reason&&!reason?{node_constructor_parameters:node.parameters.map(p=>p.type?.getText(source)??'unknown')}:{};
  if(!ts.isMethodDeclaration(node)) return {};
  const error=owner.reason||reason||(modifier(node,ts.SyntaxKind.StaticKeyword)?'static method requires a static access fixture':'');
  return {node_receiver_class:owner.name,node_receiver_eligible:!error,node_receiver_reason:error,
    node_class_capture_offset:owner.capture,node_class_methods:owner.methods,node_class_roots:owner.statics};
}
function functionInfo(node,depth,names,owner) {
  const local=nodeName(node);
  const accessor=ts.isGetAccessorDeclaration(node)?'get ':ts.isSetAccessorDeclaration(node)?'set ':'';
  const location=source.getLineAndCharacterOfPosition(node.getStart(source));
  const unsupported=callableReason(node);
  const metadata=receiverMetadata(node,owner,unsupported);
  const reason=metadata.node_receiver_eligible?'instance method requires a receiver fixture':
    metadata.node_receiver_reason||unsupported||(depth||!ts.isFunctionDeclaration(node)?'nested function, method or closure needs an access fixture':'');
  return {name:[...names,accessor+local].join('.'),line:location.line+1,column:location.character,
    parameters:node.parameters.map(p=>p.type?.getText(source)??'unknown'),output:node.type?.getText(source)??'unknown',
    reason,async:modifier(node,ts.SyntaxKind.AsyncKeyword),...metadata};
}
function visit(node, depth = 0, names = [], owner = undefined) {
  if(ts.isClassLike(node)) {
    const info=classInfo(node);
    ts.forEachChild(node,child=>visit(child,depth+1,[...names,info.name],info));
    return;
  }
  if (ts.isFunctionLike(node)) {
    const local=nodeName(node);
    functions.push(functionInfo(node,depth,names,owner));
    ts.forEachChild(node, child => visit(child, depth + 1,[...names,local]));
    return;
  }
  if (depth === 0 && ts.isVariableStatement(node)) {
    for (const d of node.declarationList.declarations) {
      globals.push({name: ts.isIdentifier(d.name)?d.name.text:'<destructured>', type: d.type?.getText(source) ?? 'dynamic'});
    }
  }
  ts.forEachChild(node, child => visit(child, depth,names,owner));
}
visit(source);
process.stdout.write(JSON.stringify({functions, globals, parser: 'TypeScript ' + ts.version,
  binding_capture_offset: Buffer.byteLength(input.source.slice(0,bindingCaptureOffset),'utf8')}));
