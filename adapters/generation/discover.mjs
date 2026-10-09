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
function reasonFor(node, depth) {
  if(depth || !ts.isFunctionDeclaration(node)) return 'nested function, method or closure needs an access fixture';
  if(node.typeParameters?.length || node.parameters.some(p => p.dotDotDotToken)) return 'generic or variadic callable needs a fixture';
  if(!node.body) return 'declaration has no source body';
  return '';
}
function visit(node, depth = 0) {
  if (ts.isFunctionLike(node)) {
    const name = node.name?.getText(source) ?? '<anonymous>';
    const location = source.getLineAndCharacterOfPosition(node.getStart(source));
    const line = location.line + 1;
    const parameters = node.parameters.map(p => p.type?.getText(source) ?? 'unknown');
    const reason = reasonFor(node, depth);
    functions.push({name, line, column: location.character, parameters, output: node.type?.getText(source) ?? 'unknown', reason,
      async: node.modifiers?.some(m => m.kind === ts.SyntaxKind.AsyncKeyword) ?? false});
    ts.forEachChild(node, child => visit(child, depth + 1));
    return;
  }
  if (depth === 0 && ts.isVariableStatement(node)) {
    for (const d of node.declarationList.declarations) {
      if (ts.isIdentifier(d.name)) globals.push({name: d.name.text, type: d.type?.getText(source) ?? 'dynamic'});
    }
  }
  ts.forEachChild(node, child => visit(child, depth));
}
visit(source);
process.stdout.write(JSON.stringify({functions, globals, parser: 'TypeScript ' + ts.version}));
