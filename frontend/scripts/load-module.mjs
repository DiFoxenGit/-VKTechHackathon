import fs from 'node:fs/promises';
import path from 'node:path';
import ts from 'typescript';

// Compile the real dependency graph in memory, without mocking domain algorithms.
export async function moduleUrl(filename, defines = {}) {
  let source = await fs.readFile(filename, 'utf8');
  for (const [key, value] of Object.entries(defines)) source = source.replaceAll(key, value);
  let compiled = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText;
  const parsed = ts.createSourceFile(filename, compiled, ts.ScriptTarget.ES2022, true, ts.ScriptKind.JS);
  for (const node of [...parsed.statements].reverse()) {
    if ((!ts.isImportDeclaration(node) && !ts.isExportDeclaration(node)) || !node.moduleSpecifier) continue;
    const specifier = node.moduleSpecifier;
    if (!specifier.text.startsWith('.')) continue;
    const resolved = path.resolve(path.dirname(filename), specifier.text + '.ts');
    const url = await moduleUrl(resolved, defines);
    compiled = compiled.slice(0, specifier.getStart(parsed)) + JSON.stringify(url) + compiled.slice(specifier.end);
  }
  return 'data:text/javascript;base64,' + Buffer.from(compiled).toString('base64');
}

export async function loadModule(filename, defines) {
  return import(await moduleUrl(filename, defines));
}
