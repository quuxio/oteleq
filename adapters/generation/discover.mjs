// Syntax inventory only: no application module is loaded.
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.argv[2] + '/adapters/node/package.json');
const ts = require('typescript');
const file = process.argv[3];
const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true);
if (source.parseDiagnostics.length) throw new Error('TypeScript parser rejected source');
const functions = [], globals = [];
function visit(node, depth = 0) {
  if (ts.isFunctionLike(node)) {
    const name = node.name?.getText(source) ?? '<anonymous>';
    const location = source.getLineAndCharacterOfPosition(node.getStart(source));
    const line = location.line + 1;
    const parameters = node.parameters.map(p => p.type?.getText(source) ?? 'unknown');
    const reason = depth || !ts.isFunctionDeclaration(node) ? 'nested function, method or closure needs an access fixture'
      : node.typeParameters?.length || node.parameters.some(p => p.dotDotDotToken) ? 'generic or variadic callable needs a fixture'
        : !node.body ? 'declaration has no source body' : '';
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
