import { cp, mkdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';

async function isDirectory(directory) {
  try {
    return (await stat(directory)).isDirectory();
  } catch (error) {
    if (error.code === 'ENOENT') return false;
    throw error;
  }
}

async function main() {
  const args = process.argv.slice(2);
  const port = Number(args[1]);
  if (args.length !== 2 || args[0] !== '--port' || !/^\d+$/.test(args[1]) || !Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('Usage: node ../../scripts/serve-next.mjs --port 3000 (run from the Next app directory).');
  }
  const appDirectory = process.cwd();
  const runtimeDirectory = path.join(appDirectory, '.next', 'standalone');
  const serverFile = path.join(runtimeDirectory, 'server.js');
  try {
    if (!(await stat(serverFile)).isFile()) throw new Error('not a file');
  } catch {
    throw new Error('Standalone build is missing. Run npm run build in this app first.');
  }
  const staticDirectory = path.join(appDirectory, '.next', 'static');
  if (!(await isDirectory(staticDirectory))) {
    throw new Error('Build assets are missing. Run npm run build in this app first.');
  }
  // Next standalone tracing omits static/public assets; its server serves them
  // after copying into the runtime folder. No build or install happens here.
  await mkdir(path.join(runtimeDirectory, '.next'), { recursive: true });
  await cp(staticDirectory, path.join(runtimeDirectory, '.next', 'static'), { recursive: true, force: true });
  const publicDirectory = path.join(appDirectory, 'public');
  if (await isDirectory(publicDirectory)) {
    await cp(publicDirectory, path.join(runtimeDirectory, 'public'), { recursive: true, force: true });
  }
  const child = spawn(process.execPath, [serverFile], {
    cwd: runtimeDirectory,
    stdio: 'inherit',
    env: { ...process.env, NODE_ENV: 'production', HOSTNAME: '127.0.0.1', PORT: String(port) },
  });
  const signalHandlers = new Map();
  for (const signal of ['SIGINT', 'SIGTERM']) {
    const handler = () => {
      if (child.exitCode === null && child.signalCode === null) child.kill(signal);
    };
    signalHandlers.set(signal, handler);
    process.on(signal, handler);
  }
  const exitCode = await new Promise(resolve => {
    child.once('error', error => {
      console.error(`[serve-next] ${error.message}`);
      resolve(1);
    });
    child.once('exit', (code, signal) => {
      resolve(code ?? (signal === 'SIGINT' ? 130 : signal === 'SIGTERM' ? 143 : 1));
    });
  });
  for (const [signal, handler] of signalHandlers) process.removeListener(signal, handler);
  process.exitCode = exitCode;
}

main().catch(error => {
  console.error(`[serve-next] ${error.message}`);
  process.exitCode = 1;
});
