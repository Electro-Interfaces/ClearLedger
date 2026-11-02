/** ROOT-only real Express composition; never dispatch a request. See dated boundary. */
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { createRequire, registerHooks, syncBuiltinESMExports } from 'node:module';
import { fileURLToPath } from 'node:url';
import cp from 'node:child_process';
import net from 'node:net';
import tls from 'node:tls';
import http from 'node:http';
import https from 'node:https';
import http2 from 'node:http2';
import dns from 'node:dns';
import dnsp from 'node:dns/promises';
import dgram from 'node:dgram';
import timers from 'node:timers';
import timerp from 'node:timers/promises';
import workers from 'node:worker_threads';
import inspector from 'node:inspector';

const raw = {
  read: fs.readFileSync.bind(fs), write: fs.writeFileSync.bind(fs),
  stat: fs.statSync.bind(fs), realpath: fs.realpathSync.bind(fs),
  exit: process.exit.bind(process), stderr: process.stderr.write.bind(process.stderr),
};
// Private output capability. No pathname argument, never passed to target/controls.
const evidenceIO = Object.freeze({
  open: fs.openSync.bind(fs), write: fs.writeSync.bind(fs), close: fs.closeSync.bind(fs),
});
const readFdIO = Object.freeze({
  open: fs.openSync.bind(fs), close: fs.closeSync.bind(fs), read: fs.readSync.bind(fs),
  fstat: fs.fstatSync.bind(fs), stat: fs.statSync.bind(fs), realpath: fs.realpathSync.bind(fs),
});
const readBindings = new Map();
const readFdCounters = { opened: 0, reads: 0, closed: 0 };
let originalEnvironment, guardedEnvironment, environmentBaseline;
let debugAbsentDeleteNoops = 0;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const require = createRequire('/work/source/package.json');
const plan = JSON.parse(raw.read('/tools/plan.json', 'utf8'));
const mode = process.argv[2];
const control = process.argv[3];
const denied = [];
const DENIED_KIND_ENUM = new Set(['UNKNOWN_DENIED_KIND', 'fs.nonpath', 'fs.credentials',
  'fs.read', 'fs.read_count', 'fs.mutation', 'uncaught', 'env.set', 'env.delete',
  'env.define', 'process.binding', 'module.permission', 'module.nonfile', 'module.native',
  'module.source', 'express.handle', 'express.listen', 'router.handle', 'route.dispatch',
  'fs.fd_unknown', 'fs.fd_identity', 'fs.fd_not_regular', 'fs.fd_flags']);
const ERROR_CODE_ENUM = new Set(['UNKNOWN', 'SUPPORT_BOUNDARY_DENIED', 'ERR_ACCESS_DENIED', 'ERR_SYSTEM_ERROR',
  'ERR_DLOPEN_DISABLED', 'ERR_DLOPEN_FAILED', 'ERR_INVALID_ARG_TYPE', 'ERR_INVALID_ARG_VALUE',
  'ERR_MODULE_NOT_FOUND', 'MODULE_NOT_FOUND', 'ERR_REQUIRE_ESM', 'ERR_UNKNOWN_FILE_EXTENSION',
  'EACCES', 'EPERM', 'ENOENT', 'EROFS', 'EBADF', 'ENOSPC', 'EMFILE', 'EFBIG', 'EEXIST',
  'EINVAL', 'EIO', 'EINTR', 'node_identity', 'source_identity', 'helper_identity', 'mode',
  'registration_method', 'layer_recorded_twice', 'intrinsic_layer_without_registration',
  'uncovered_intrinsic_layer', 'actual_app', 'layer_count', 'caught_attempt', 'output_budget',
  'control_unknown', 'control_did_not_deny', 'evidence_write_short', 'fd_binding_leak',
  'fd_control_mode', 'fd_control_reuse_not_exact', 'fd_positive_bytes',
  'env_snapshot_changed', 'env_positive_state', 'native_interface_denial_expected']);
const reads = new Set();
const loaded = new Set();
const ensure = (ok, code) => { if (!ok) throw Object.assign(new Error(code), { code }); };
const deny = kind => {
  denied.push(DENIED_KIND_ENUM.has(kind) ? kind : 'UNKNOWN_DENIED_KIND');
  if (denied.length > 128) raw.exit(82);
  throw Object.assign(new Error(`boundary:${kind}`), { code: 'SUPPORT_BOUNDARY_DENIED' });
};
const replace = (obj, key, fn) => {
  if (typeof obj?.[key] === 'function') obj[key] = fn;
};
const block = (obj, keys, kind) => {
  for (const key of keys) {
    const identifier = `${kind}.${key}`;
    DENIED_KIND_ENUM.add(identifier); // fixed built-in method selection, no target args
    replace(obj, key, function () { return deny(identifier); });
  }
};

function safeCode(error) {
  try { return typeof error?.code === 'string' && ERROR_CODE_ENUM.has(error.code) ? error.code : 'UNKNOWN'; }
  catch { return 'UNKNOWN'; }
}
function safeDenied() {
  return denied.map(kind => DENIED_KIND_ENUM.has(kind) ? kind : 'UNKNOWN_DENIED_KIND');
}
function writeEvidence(value) {
  const bytes = Buffer.from(JSON.stringify(value) + '\n', 'utf8');
  ensure(bytes.length <= plan.payloadBudgetBytes, 'output_budget');
  const fd = evidenceIO.open('/evidence/result.json', 'wx', 0o600);
  try {
    let offset = 0;
    while (offset < bytes.length) {
      const count = evidenceIO.write(fd, bytes, offset, bytes.length - offset);
      ensure(Number.isInteger(count) && count > 0 && count <= bytes.length - offset, 'evidence_write_short');
      offset += count;
    }
  } finally { evidenceIO.close(fd); }
}

// Capture real permission APIs for no-app controls BEFORE wrappers. Not exposed to target.
const controlsRaw = {
  read: raw.read, write: raw.write, spawn: cp.spawnSync.bind(cp),
  dlopen: process.dlopen.bind(process), Worker: workers.Worker,
  execve: process.execve?.bind(process), connect: net.connect.bind(net),
  replaceOwnedReadFDForControl(fd) {
    ensure(mode === 'negative' && control === 'guard-fd-reused', 'fd_control_mode');
    ownedReadFD(fd); // never close an unknown or already stale descriptor
    readFdIO.close(fd);
    const next = readFdIO.open('/tools/plan.json', 'r');
    if (next !== fd) {
      readFdIO.close(next);
      readBindings.delete(fd);
      throw Object.assign(new Error('fd_control_reuse_not_exact'), { code: 'fd_control_reuse_not_exact' });
    }
    return next;
  },
};
Error.stackTraceLimit = 40;

function filename(value) {
  if (value instanceof URL) value = fileURLToPath(value);
  if (Buffer.isBuffer(value)) value = value.toString();
  if (typeof value !== 'string') return deny('fs.nonpath');
  return path.resolve(value);
}
function readable(value) {
  const p = filename(value);
  if (p.split('/').some(s => /^\.env(?:\.|$)|^\.(?:ssh|vault|claude|aws|npmrc)$|credentials/i.test(s))) {
    return deny('fs.credentials');
  }
  const yes = p === '/work/source' || p.startsWith('/work/source/') ||
    p === '/work/node_modules' || p.startsWith('/work/node_modules/') ||
    p === '/tools' || p.startsWith('/tools/') || p === '/tmp' || p.startsWith('/tmp/');
  if (!yes) return deny('fs.read');
  reads.add(p);
  if (reads.size > 50000) return deny('fs.read_count');
  return p;
}
function writable(value) {
  const p = filename(value);
  if (!p.startsWith('/tmp/')) return deny('fs.mutation');
  return p;
}
function fileIdentity(info) {
  const fields = ['dev','ino','mode','size','mtimeNs','ctimeNs'].map(key => info[key]);
  if (!fields.every(value => typeof value === 'bigint')) return deny('fs.fd_identity');
  return fields;
}
function sameIdentity(info, identity) {
  return info.isFile() && fileIdentity(info).every((value, index) => value === identity[index]);
}
function ownedReadFD(fd) {
  if (!Number.isInteger(fd) || fd < 3 || !readBindings.has(fd)) return deny('fs.fd_unknown');
  const record = readBindings.get(fd);
  let info, currentPath, currentFile;
  try {
    info = readFdIO.fstat(fd, { bigint: true });
    currentPath = readFdIO.realpath(record.path);
    currentFile = readFdIO.stat(record.path, { bigint: true });
  } catch { return deny('fs.fd_identity'); }
  readable(record.path); readable(currentPath);
  if (currentPath !== record.realpath || !sameIdentity(info, record.identity) ||
      !sameIdentity(currentFile, record.identity)) return deny('fs.fd_identity');
  return record;
}
function readFdSummary() { return { ...readFdCounters, active: readBindings.size }; }
function environmentState(env) {
  const keys = Object.keys(env).sort();
  return { sha256: hash(JSON.stringify(keys.map(key => [key, env[key]]))), keyCount: keys.length };
}
function environmentSummary() {
  ensure(process.env === guardedEnvironment, 'env_snapshot_changed');
  const current = environmentState(originalEnvironment);
  ensure(current.sha256 === environmentBaseline.sha256 && current.keyCount === environmentBaseline.keyCount,
    'env_snapshot_changed');
  return { ...current, unchanged: true, objectIdentityPreserved: true, debugAbsentDeleteNoops };
}
function installGuards() {
  for (const [obj, prefix] of [[fs, 'fs'], [fsp, 'fsp']]) {
    for (const key of ['readFile','readFileSync','stat','statSync','lstat','lstatSync',
      'access','accessSync','existsSync','readdir','readdirSync','realpath','realpathSync',
      'readlink','readlinkSync','opendir','opendirSync','createReadStream']) {
      const original = obj[key];
      if (typeof original === 'function') obj[key] = function (...args) {
        readable(args[0]); return Reflect.apply(original, this, args);
      };
    }
    // These FD methods remain denied. Only owned regular-file readSync is allowed below.
    block(obj, ['read','readv','readvSync','write','writeSync','writev','writevSync',
      'ftruncate','ftruncateSync','fchmod','fchmodSync','fchown','fchownSync','futimes',
      'futimesSync','watch','watchFile','unwatchFile'], prefix);
    for (const key of ['writeFile','writeFileSync','appendFile','appendFileSync','mkdir',
      'mkdirSync','rm','rmSync','rmdir','rmdirSync','unlink','unlinkSync','truncate',
      'truncateSync','chmod','chmodSync','chown','chownSync','utimes','utimesSync',
      'lutimes','lutimesSync','lchown','lchownSync','createWriteStream','mkdtemp','mkdtempSync']) {
      const original = obj[key];
      if (typeof original === 'function') obj[key] = function (...args) {
        writable(args[0]); return Reflect.apply(original, this, args);
      };
    }
    for (const key of ['rename','renameSync','copyFile','copyFileSync','cp','cpSync',
      'link','linkSync','symlink','symlinkSync']) {
      const original = obj[key];
      if (typeof original === 'function') obj[key] = function (...args) {
        writable(args[0]); writable(args[1]); return Reflect.apply(original, this, args);
      };
    }
    for (const key of ['open', 'openSync']) {
      const original = obj[key];
      if (typeof original === 'function') obj[key] = function (...args) {
        const flags = args[1] ?? 'r';
        if (obj === fs && key === 'openSync') {
          if (flags !== 'r' && flags !== 0) return deny('fs.fd_flags');
          const p = readable(args[0]);
          const fd = Reflect.apply(original, this, args);
          try {
            if (readBindings.has(fd)) {
              readBindings.delete(fd);
              return deny('fs.fd_identity');
            }
            const info = readFdIO.fstat(fd, { bigint: true });
            const realpath = readFdIO.realpath(p);
            readable(realpath);
            if (fd < 3 || !info.isFile()) return deny('fs.fd_not_regular');
            readBindings.set(fd, Object.freeze({ path: p, realpath, identity: Object.freeze(fileIdentity(info)) }));
            readFdCounters.opened++;
            return fd;
          } catch (error) { readFdIO.close(fd); throw error; }
        }
        if (flags !== 'r' && flags !== 0) writable(args[0]); else readable(args[0]);
        return Reflect.apply(original, this, args);
      };
    }
  }
  fs.readSync = function (fd, ...args) {
    ownedReadFD(fd);
    const result = Reflect.apply(readFdIO.read, this, [fd, ...args]);
    readFdCounters.reads++;
    return result;
  };
  fs.closeSync = function (fd, ...args) {
    if (!readBindings.has(fd)) return deny('fs.fd_unknown');
    readBindings.delete(fd);
    readFdCounters.closed++;
    return Reflect.apply(readFdIO.close, this, [fd, ...args]);
  };
  block(cp, ['exec','execSync','execFile','execFileSync','spawn','spawnSync','fork'], 'process');
  block(process, ['dlopen','execve','loadEnvFile','chdir','chroot','setuid','seteuid','setgid','setegid',
    'setgroups','initgroups','kill','abort','exit'], 'process');
  block(workers, ['Worker'], 'worker');
  block(inspector, ['open','Session'], 'inspector');
  block(process.report, ['writeReport'], 'process.report');
  block(net, ['connect','createConnection','createServer'], 'net');
  block(net.Socket.prototype, ['connect'], 'net.Socket');
  block(net.Server.prototype, ['listen'], 'net.Server');
  block(tls, ['connect','createServer'], 'tls');
  for (const [obj, kind] of [[http,'http'],[https,'https'],[http2,'http2']]) {
    block(obj, ['request','get','connect','createServer','createSecureServer'], kind);
    block(obj.Server?.prototype, ['listen'], `${kind}.Server`);
  }
  block(dgram, ['createSocket'], 'dgram');
  for (const obj of [dns, dnsp]) {
    block(obj, Object.keys(obj).filter(k => /^(lookup|resolve|reverse|setServers)/.test(k)), 'dns');
    block(obj.Resolver?.prototype, Object.getOwnPropertyNames(obj.Resolver?.prototype || {})
      .filter(k => /^(resolve|reverse|setServers)/.test(k)), 'dns.Resolver');
  }
  for (const obj of [globalThis, timers, timerp]) {
    block(obj, ['setTimeout','setInterval','setImmediate'], 'timer');
  }
  block(timerp.scheduler, ['wait','yield'], 'timer.scheduler');
  block(globalThis, ['fetch','WebSocket','EventSource'], 'network');
  block(AbortSignal, ['timeout'], 'timer.AbortSignal');
  // A denial caught by target must remain visible in final evidence.
  process.on('uncaughtExceptionMonitor', () => { denied.push('uncaught'); });
  const binding = process.binding.bind(process);
  process.binding = function (name) {
    if (['tcp_wrap','udp_wrap','pipe_wrap','cares_wrap','spawn_sync','process_wrap',
      'fs','worker','inspector'].includes(name)) return deny('process.binding');
    return binding(name);
  };
  const env = process.env;
  originalEnvironment = env;
  environmentBaseline = environmentState(env);
  const debugInitiallyAbsent = !Object.hasOwn(env, 'DEBUG');
  guardedEnvironment = new Proxy(env, {
    set() { return deny('env.set'); },
    deleteProperty(_target, key) {
      if (key === 'DEBUG' && debugInitiallyAbsent && !Object.hasOwn(env, 'DEBUG')) {
        debugAbsentDeleteNoops++;
        return true; // No deletion or other mutation: debug's absent-key startup operation.
      }
      return deny('env.delete');
    },
    defineProperty() { return deny('env.define'); },
  });
  process.env = guardedEnvironment;
  registerHooks({
    resolve(specifier, context, nextResolve) {
      let result;
      try { result = nextResolve(specifier, context); }
      catch (error) {
        if (error.code === 'ERR_ACCESS_DENIED') denied.push('module.permission');
        throw error;
      }
      if (result.url.startsWith('node:')) return result;
      if (!result.url.startsWith('file:')) return deny('module.nonfile');
      const file = readable(new URL(result.url));
      if (file.endsWith('.node')) return deny('module.native');
      if (file.startsWith('/work/source/')) {
        const name = file.slice('/work/source/'.length);
        if (!Object.hasOwn(plan.staticNodes, name) && name !== 'package.json') return deny('module.source');
      }
      loaded.add(file);
      return result;
    },
  });
  syncBuiltinESMExports();
}

function identityBefore() {
  ensure(hash(raw.read('/bin/node')) === plan.node.sha256, 'node_identity');
  for (const [name, record] of Object.entries(plan.staticNodes)) {
    ensure(hash(raw.read(`/work/source/${name}`)) === record.sha256, 'source_identity');
  }
  for (const [name, record] of Object.entries(plan.helpers)) {
    ensure(hash(raw.read(`/tools/${name}`)) === record.sha256, 'helper_identity');
  }
}

function pathValue(value) {
  if (value === undefined) return { kind: 'undefined' };
  if (typeof value === 'string') return { kind: 'string', value };
  if (value instanceof RegExp) return { kind: 'regexp', source: value.source, flags: value.flags };
  if (Array.isArray(value)) return { kind: 'array', values: value.map(pathValue) };
  return { kind: 'unresolved', type: typeof value };
}
function provenance() {
  // Stack contains only file/line references. No args, values, environment or messages.
  return new Error().stack.split('\n').slice(2).map(line => line.trim())
    .filter(line => /\/(work\/source|work\/node_modules)\//.test(line)).slice(0, 8);
}

async function exportComposition() {
  const express = require('express');
  const Router = require('router');
  const Route = require('router/lib/route');
  const pg = require('pg');
  for (const klass of [pg.Pool, pg.Client]) {
    block(klass?.prototype, ['connect','query','end'], 'SQL');
  }
  const metadata = new WeakMap();
  const registrations = [];
  const seenReceivers = new Set();
  const originalHandle = express.application.handle;
  replace(express.application, 'handle', () => deny('express.handle'));
  replace(Router.prototype, 'handle', () => deny('router.handle'));
  replace(Route.prototype, 'dispatch', () => deny('route.dispatch'));
  replace(express.application, 'listen', () => deny('express.listen'));
  function wrap(proto, name, layerKind) {
    const original = proto[name];
    ensure(typeof original === 'function', 'registration_method');
    proto[name] = function (...args) {
      const start = Array.isArray(this.stack) ? this.stack.length : 0;
      const source = provenance();
      const result = Reflect.apply(original, this, args);
      seenReceivers.add(this);
      const added = this.stack.slice(start);
      let mountPath = args[0];
      if (layerKind === 'mount') {
        let first = args[0];
        while (Array.isArray(first) && first.length) first = first[0];
        if (typeof first === 'function') mountPath = '/';
      }
      const entry = { ordinal: registrations.length, method: name, layerKind,
        path: layerKind === 'routeHandler' ? pathValue(this.path) : pathValue(mountPath),
        source, added: added.length };
      registrations.push(entry);
      for (const layer of added) {
        ensure(!metadata.has(layer), 'layer_recorded_twice');
        metadata.set(layer, entry);
      }
      return result;
    };
  }
  wrap(Router.prototype, 'use', 'mount');
  wrap(Router.prototype, 'route', 'route');
  for (const method of [...http.METHODS.map(x => x.toLowerCase()), 'all']) {
    if (typeof Route.prototype[method] === 'function') wrap(Route.prototype, method, 'routeHandler');
  }
  const { createSupportApp } = await import('file:///work/source/scripts/app.js');
  const config = {
    corsOrigins: ['https://composition.invalid'], uploadsPath: '/tmp/uploads',
    distPath: plan.variant.dist ? '/tmp/dist' : null,
    contextEntry: {
      directory: '/tmp/dist-context', isEnabled: () => plan.variant.context,
      getNodeOrigin: () => 'https://node.invalid', getCcOrigin: () => 'https://cc.invalid',
      allowLoopbackHttp: () => false,
    }, supportContext: { isEnabled: () => plan.variant.context },
  };
  const app = createSupportApp(config, { auditPool: undefined });
  ensure(app.handle !== originalHandle && Array.isArray(app.router.stack), 'actual_app');
  let totalLayers = 0;
  const sourceFiles = [...new Set([...Object.keys(plan.staticNodes).map(p => `/work/source/${p}`),
    ...Object.keys(require.cache).filter(p => p.startsWith('/work/node_modules/') && p.endsWith('.js'))])]
    .map(file => ({ file, bytes: raw.read(file, 'utf8') }));
  const definitions = new Map();
  function handler(fn, registration) {
    const text = Function.prototype.toString.call(fn);
    const digest = hash(text);
    if (!definitions.has(digest)) {
      const matches = [];
      for (const { file, bytes } of sourceFiles) {
        const at = bytes.indexOf(text);
        if (at !== -1) matches.push({ file, line: bytes.slice(0, at).split('\n').length,
          fileSHA256: hash(bytes), match: 'exact Function.toString source text' });
        if (matches.length > 16) break;
      }
      definitions.set(digest, matches);
    }
    const matches = definitions.get(digest);
    return { name: fn.name || null, arity: fn.length, sha256: digest,
      registrationSource: registration?.source || [],
      definitionSource: matches.length === 1 ? matches[0] : null,
      definitionCandidates: matches.length === 1 ? [] : matches,
      unresolved: matches.length === 1 ? null : 'definition text missing or ambiguous; registration frame is not definition location' };
  }
  function walk(stack, chain, active) {
    return stack.map((layer, index) => {
      ensure(++totalLayers <= 12000, 'layer_count');
      const registration = metadata.get(layer);
      ensure(registration, 'intrinsic_layer_without_registration');
      const entry = { index, registrationOrdinal: registration.ordinal,
        path: registration.path, mountChain: chain,
        routePath: layer.route ? pathValue(layer.route.path) : null,
        methods: layer.route ? Object.keys(layer.route.methods) : layer.method ? [layer.method] : [],
        keys: layer.keys || [], slash: layer.slash ?? null,
        handler: handler(layer.handle, registration), children: null };
      const child = layer.route || (Array.isArray(layer.handle?.stack) ? layer.handle : null);
      if (child) {
        if (active.has(child)) entry.children = { unresolved: 'cycle' };
        else entry.children = walk(child.stack, [...chain, registration.path], new Set([...active, child]));
      }
      return entry;
    });
  }
  const stack = walk(app.router.stack, [], new Set([app.router]));
  // All receivers, including unmounted factory routers, retain intrinsic registration coverage.
  let intrinsicLayers = 0;
  for (const receiver of seenReceivers) for (const layer of receiver.stack) {
    intrinsicLayers++;
    ensure(metadata.has(layer), 'uncovered_intrinsic_layer');
  }
  ensure(denied.length === 0, 'caught_attempt');
  ensure(readBindings.size === 0, 'fd_binding_leak');
  return { schemaVersion: 1, status: 'EXPORTED_REGISTRATION_ONLY', variant: plan.variant,
    sourceIdentity: plan.sourceIdentity, nodeIdentity: plan.node,
    registrations, stack, totalLayers, intrinsicLayers, receiverCount: seenReceivers.size,
    reads: [...reads].sort(), loaded: [...loaded].sort(), denied, readFD: readFdSummary(),
    environmentAudit: environmentSummary(),
    limitations: ['No HTTP requests, auth/ACL conformance or SQL success',
      'No live/container/public/native SSH behavior proof',
      'Unresolved definition locations are preserved; registration provenance is independent'],
  };
}

async function main() {
  identityBefore();
  installGuards();
  if (mode === 'negative') {
    const { runControl } = await import('file:///tools/support-composition-negative.mjs');
    ensure(readBindings.size === 0, 'fd_binding_leak');
    const result = await runControl(control, { raw: controlsRaw, deny });
    ensure(readBindings.size === 0, 'fd_binding_leak');
    return { schemaVersion: 1, status: 'NEGATIVE_CONTROL', control, result, denied,
      readFD: readFdSummary(), environmentAudit: environmentSummary() };
  }
  ensure(mode === 'export', 'mode');
  return await exportComposition();
}
try {
  const result = await main();
  writeEvidence(result);
  raw.exit(0);
} catch (error) {
  // Never publish arbitrary target error messages, objects, headers or args.
  const result = { schemaVersion: 1, status: 'INVALID', code: safeCode(error), denied: safeDenied(), readFD: readFdSummary() };
  let writerCode = null;
  try { writeEvidence(result); }
  catch (writerError) { writerCode = safeCode(writerError); }
  raw.stderr('SUPPORT_COMPOSITION_INVALID ' + JSON.stringify({ code: result.code,
    writerCode, denied: safeDenied() }) + '\n');
  raw.exit(80);
}
