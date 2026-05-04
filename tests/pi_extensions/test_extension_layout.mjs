import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const EXT_DIR = '.pi/extensions';

test('project-local pi extensions do not expose helper ts files at top level', () => {
  const entries = readdirSync(EXT_DIR);
  const topLevelTsFiles = entries.filter((name) => name.endsWith('.ts'));

  assert.deepEqual(
    topLevelTsFiles,
    [],
    `Top-level .pi/extensions/*.ts files are auto-discovered as extensions. Move helper modules under an extension directory with index.ts. Found: ${topLevelTsFiles.join(', ')}`,
  );
});

test('model-router-v2 extension uses directory entrypoint layout', () => {
  const entryPath = join(EXT_DIR, 'model-router-v2', 'index.ts');
  assert.equal(statSync(entryPath).isFile(), true);
});
