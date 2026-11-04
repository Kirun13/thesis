import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const runs = path.join(root, 'runs');
const current = path.join(runs, 'active.json');
const command = process.argv[2];
fs.mkdirSync(runs, { recursive: true });
const alive = pid => { try { process.kill(pid, 0); return true; } catch { return false; } };
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));

if (command === 'start') {
  if (fs.existsSync(current)) {
    const existing = read(current);
    if (alive(existing.pid)) throw new Error(`Run already active: PID ${existing.pid}, ${existing.runDir}`);
  }
  const resume = process.argv[3];
  const runDir = resume ? path.resolve(root, resume) : path.join(runs, `overnight-${new Date().toISOString().replace(/[:.]/g, '-')}`);
  fs.mkdirSync(runDir, { recursive: true });
  const stop = path.join(runDir, 'STOP');
  if (fs.existsSync(stop)) fs.unlinkSync(stop);
  const out = fs.openSync(path.join(runDir, 'console.log'), 'a');
  const child = spawn('python', ['-u', 'scripts/train.py', '--profile', 'overnight', '--run-dir', runDir], {
    cwd: root, detached: true, windowsHide: true, stdio: ['ignore', out, out],
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
  });
  child.on('error', error => { console.error(error); process.exitCode = 1; });
  child.unref();
  fs.closeSync(out);
  const state = { pid: child.pid, runDir, started: new Date().toISOString() };
  fs.writeFileSync(current, JSON.stringify(state, null, 2));
  console.log(JSON.stringify(state, null, 2));
} else if (['status', 'stop'].includes(command)) {
  if (!fs.existsSync(current)) { console.log('No run registered.'); process.exit(0); }
  const state = read(current);
  if (command === 'stop') fs.writeFileSync(path.join(state.runDir, 'STOP'), 'Stop requested.');
  const statusFile = path.join(state.runDir, 'status.json');
  console.log(JSON.stringify({ ...state, processAlive: alive(state.pid),
    status: fs.existsSync(statusFile) ? read(statusFile) : 'starting' }, null, 2));
  if (command === 'status') {
    const log = path.join(state.runDir, 'console.log');
    if (fs.existsSync(log)) console.log(fs.readFileSync(log, 'utf8').split(/\r?\n/).slice(-12).join('\n'));
  }
} else throw new Error('Use start [existing-run-directory], status, or stop.');
