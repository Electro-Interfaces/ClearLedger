/** No target import. Each case runs in its own ROOT-isolated process. */
import fs from 'node:fs';
import cp from 'node:child_process';
import net from 'node:net';
import dns from 'node:dns';
import workers from 'node:worker_threads';
import timers from 'node:timers';
import os from 'node:os';

export async function runControl(name, { raw }) {
  if (name === 'native-interface-feature-denial') {
    try { os.networkInterfaces(); }
    catch (error) {
      // Exact pinned Node 22.23.2 source passes positive errno to uv_err_name.
      // Validate fields, publish fixed constants only; never error.message/info.message.
      if (error.code === 'ERR_SYSTEM_ERROR' && error.info?.errno === 1 &&
          error.info?.syscall === 'uv_interface_addresses' && error.info?.code === 'Unknown system error 1') {
        return { positive: true, denied: false, nativeDenied: true,
          error: { code: 'ERR_SYSTEM_ERROR', errno: 1, syscall: 'uv_interface_addresses',
            infoCode: 'Unknown system error 1' } };
      }
    }
    throw Object.assign(new Error('native_interface_denial_expected'), { code: 'native_interface_denial_expected' });
  }
  if (name === 'fd-owned-read') {
    const fd = fs.openSync('/tmp/fd-read-sentinel', 'r');
    try {
      const bytes = Buffer.alloc(128);
      const count = fs.readSync(fd, bytes, 0, bytes.length, 0);
      const again = fs.readSync(fd, bytes, 0, bytes.length, 0);
      if (count !== again || bytes.subarray(0, count).toString() !== 'support-composition-read-only-fd-v8\n') {
        throw Object.assign(new Error('fd_positive_bytes'), { code: 'fd_positive_bytes' });
      }
      return { positive: true, denied: false, bytes: count };
    } finally { fs.closeSync(fd); }
  }
  if (name === 'env-debug-absent-delete') {
    if (Object.hasOwn(process.env, 'DEBUG')) throw Object.assign(new Error('env_positive_state'), { code: 'env_positive_state' });
    const first = delete process.env.DEBUG;
    const second = delete process.env.DEBUG;
    if (!first || !second || Object.hasOwn(process.env, 'DEBUG')) {
      throw Object.assign(new Error('env_positive_state'), { code: 'env_positive_state' });
    }
    return { positive: true, denied: false, noopDeletes: 2 };
  }
  const actions = {
    'guard-network': () => net.connect({ host: '192.0.2.1', port: 9 }),
    'guard-dns': () => dns.lookup('composition.invalid', () => {}),
    'guard-process': () => cp.spawn('/bin/node', ['--version']),
    'guard-execve': () => process.execve('/bin/node', ['/bin/node', '--version'], {}),
    'guard-read': () => fs.readFileSync('/denied/sentinel'),
    'guard-envfile': () => fs.readFileSync('/tmp/.env'),
    'guard-loadenv': () => process.loadEnvFile('/tmp/.env'),
    'guard-write': () => fs.writeFileSync('/work/source/negative', 'synthetic'),
    'guard-native': () => process.dlopen({ exports: {} }, '/tmp/probe.node'),
    'guard-worker': () => new workers.Worker('process.exit(0)', { eval: true }),
    'guard-timer': () => timers.setTimeout(() => {}, 1000).unref(),
    'permission-read': () => raw.read('/denied/sentinel', 'utf8'),
    'permission-write': () => raw.write('/denied/output', 'synthetic'),
    'permission-process': () => raw.spawn('/bin/node', ['--version']),
    'permission-execve': () => raw.execve('/bin/node', ['/bin/node', '--version'], {}),
    'permission-native': () => raw.dlopen({ exports: {} }, '/tmp/probe.node'),
    'permission-worker': () => new raw.Worker('0', { eval: true }),
    'guard-fd-unknown': () => fs.readSync(0, Buffer.alloc(1), 0, 1, 0),
    'guard-fd-closed': () => {
      const fd = fs.openSync('/tmp/fd-read-sentinel', 'r');
      fs.closeSync(fd);
      fs.readSync(fd, Buffer.alloc(1), 0, 1, 0);
    },
    'guard-fd-reused': () => {
      const fd = fs.openSync('/tmp/fd-read-sentinel', 'r');
      let exactReuse = false;
      try {
        raw.replaceOwnedReadFDForControl(fd);
        exactReuse = true;
        fs.readSync(fd, Buffer.alloc(1), 0, 1, 0);
      } finally { if (exactReuse) fs.closeSync(fd); }
    },
    'guard-fd-write': () => {
      const fd = fs.openSync('/tmp/fd-read-sentinel', 'r');
      try { fs.writeSync(fd, Buffer.from('forbidden'), 0, 9, 0); }
      finally { fs.closeSync(fd); }
    },
    'guard-env-delete-existing': () => {
      if (!Object.hasOwn(process.env, 'JWT_SECRET')) throw Object.assign(new Error('env_positive_state'), { code: 'env_positive_state' });
      delete process.env.JWT_SECRET;
    },
  };
  if (!Object.hasOwn(actions, name)) throw Object.assign(new Error('control'), { code: 'control_unknown' });
  let code;
  try { actions[name](); }
  catch (error) { code = error.code; }
  const allowed = name.startsWith('guard-') ? ['SUPPORT_BOUNDARY_DENIED']
    : name === 'permission-native' ? ['ERR_DLOPEN_DISABLED', 'ERR_ACCESS_DENIED'] : ['ERR_ACCESS_DENIED'];
  if (!allowed.includes(code)) throw Object.assign(new Error('control_did_not_deny'), { code: 'control_did_not_deny' });
  return { denied: true, code };
}
