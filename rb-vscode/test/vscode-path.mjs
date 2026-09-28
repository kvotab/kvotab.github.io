// Prints the path of a VS Code build for the integration tests, downloading
// it into .vscode-test/ the first time:  node test/vscode-path.mjs 1.135.0
import { downloadAndUnzipVSCode } from '@vscode/test-electron';

const version = process.argv[2] || 'stable';
console.log(await downloadAndUnzipVSCode(version));
