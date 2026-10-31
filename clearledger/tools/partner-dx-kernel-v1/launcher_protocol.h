/* SOURCE / NOTRUN. Linux x86_64 only. Wire integers are little endian;
 * never transmit a C struct (padding and host byte order are not the ABI).
 * Trusted Python <-> native broker uses stdin/stdout, candidate output is data.
 */
#ifndef DX_KERNEL_LAUNCHER_PROTOCOL_H
#define DX_KERNEL_LAUNCHER_PROTOCOL_H
#include <stdint.h>
#define DX_MAGIC "DXK1"
#define DX_VERSION 1U
#define DX_HEADER_BYTES 16U
#define DX_CONFIG_FIELDS 25U
#define DX_FRAME_MAX (2U * 1024U * 1024U)
#define DX_RECEIPT_MAX 65536U
#define DX_PROC_MAX 131072U
#define DX_OUTPUT_CHUNK 16384U
#define DX_OUTPUT_MAX 8388608U
#define DX_POOL_BYTES 67108864U
#define DX_POOL_INODES 133U
#define DX_POOL_ENTRIES 128U
#define DX_FILE_MAX 16777216U
/* Read-only executable hashing is not a candidate writable-file allowance. */
#define DX_RUNTIME_ELF_MAX 67108864U
#define DX_MEMORY_MAX 2147483648ULL
#define DX_FLOOR_BYTES 8589934592ULL
#define DX_WALL_MS 180000ULL
#define DX_INTERVAL_MS 1000ULL
#define DX_GAP_MS 1500ULL
#define DX_EXEC_FD 96
#define DX_BOOT_FD 97
enum dx_opcode { DX_CONFIG=1, DX_READY=2, DX_SEAL=3, DX_EXEC=4,
 DX_STDOUT=5, DX_STDERR=6, DX_EXIT=7, DX_ERROR=8, DX_CANCEL=9,
 DX_FINALIZE=10, DX_FINAL=11 };
/* CONFIG: u32 count then count LP strings, LP = u32 length + ASCII bytes.
 * No NUL/empty/unknown/trailing fields. Max string length 4095.
 * Rootfs is independently prepared and pinned, never built by this program.
 * Source/native/venv retain the exact absolute paths used by PR91.
 */
enum dx_config_field {
 DX_ROOTFS, DX_SOURCE, DX_NATIVE, DX_VENV, DX_CACHE_HOST, DX_CACHE_GUEST,
 DX_POLICY_HOST, DX_POOL, DX_HOME, DX_UID, DX_GID, DX_GIT_DIR, DX_GIT_COMMON,
 DX_STORAGE_PATH, DX_STORAGE_ID, DX_PYTHON_SHA, DX_POLICY_SHA,
 DX_ROOTFS_DIGEST, DX_RUNNER_SHA, DX_SOURCE_HEAD, DX_SOURCE_BRANCH,
 DX_CONTROLLER_SHA, DX_ADMISSION_HOST, DX_CGROUP_PARENT, DX_HOST_EVIDENCE
};
/* SEAL: u32 admission_length, canonical raw A bytes (including LF), u32 env_count,
 * sorted LP key + LP value pairs. No inherited environment. Native computes
 * SHA(A), writes the already-open external writer, fsyncs and closes it.
 * READY/EXEC/EXIT/ERROR: canonical ASCII JSON + LF. All measurement fields
 * reflect native observations; missing primitives always reject.
 * READY: candidate,namespaces,mounts,quota,host_floor,controller,runtime.
 * runtime: mountinfo_base64,status_base64,python_sha256,policy_sha256,
 * rootfs_digest,reservation_bytes,reservation_entries,rlimits,cgroup,
 * pool_capacity_bytes,pool_files. Proc decoded sizes each <=131072.
 * EXEC: consumed,continue_count,exec_observed,notification_id,pid.
 * EXIT: exit_code,termination_signal,output_bytes,host_floor,artifacts_copied,
 * reservation_bytes,reservation_entries,exec_observed,continue_count,rejected.
 * host_floor final: storage_id,before_free,minimum_observed_during_free,
 * after_free,samples,max_gap_ms,status. Before sample uses CLOCK_MONOTONIC_MS.
 * stdout/stderr payloads are raw bounded bytes, never protocol input or JSON.
 * Four physical unnamed reservations: output 8388608, metadata 4194304,
 * external final 65536, manifest 65536 = 12713984 bytes, four entry slots.
 * EXIT is provisional after candidate wait/copy, native monitoring continues.
 * FINALIZE payload: four zero bytes. FINAL has the same keys as EXIT; final
 * native trace has been persisted/copied, monitoring finishes, broker exits.
 * Git config fields are outside provenance only, never candidate mounts.
 * Directional sequences start at 1, increase by 1, never wrap.
 */
#endif
