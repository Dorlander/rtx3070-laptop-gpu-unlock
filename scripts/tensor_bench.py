#!/usr/bin/env python3
# FP16 tensor-core throughput microbenchmark via the CUDA Driver API (nvcuda.dll).
# No CUDA toolkit / no PyTorch: the driver JITs the embedded PTX. Works on Python 3.14.
# A tight warp-level mma.sync.m16n8k16 (f16 in, f32 accumulate) loop; many warps hide
# latency so tensor cores saturate. The gpu-unlock speed unlock ~doubles this rate.
import ctypes as C, time, sys

PTX = b"""
.version 7.5
.target sm_86
.address_size 64
.visible .entry bench(.param .u64 outp, .param .u32 iters)
{
  .reg .pred %p;
  .reg .b32  %a0,%a1,%a2,%a3,%b0,%b1,%cnt,%lim,%tx,%cx,%nx,%gid;
  .reg .f32  %c0,%c1,%c2,%c3;
  .reg .b64  %base,%off,%ptr;
  ld.param.u64 %base, [outp];
  ld.param.u32 %lim,  [iters];
  mov.b32 %a0, 0x3c003c00; mov.b32 %a1, 0x3c003c00;
  mov.b32 %a2, 0x3c003c00; mov.b32 %a3, 0x3c003c00;
  mov.b32 %b0, 0x3c003c00; mov.b32 %b1, 0x3c003c00;
  mov.f32 %c0, 0f00000000; mov.f32 %c1, 0f00000000;
  mov.f32 %c2, 0f00000000; mov.f32 %c3, 0f00000000;
  mov.u32 %cnt, 0;
$L:
  mma.sync.aligned.m16n8k16.row.col.f32.f16.f16.f32
     {%c0,%c1,%c2,%c3}, {%a0,%a1,%a2,%a3}, {%b0,%b1}, {%c0,%c1,%c2,%c3};
  add.u32 %cnt, %cnt, 1;
  setp.lt.u32 %p, %cnt, %lim;
  @%p bra $L;
  mov.u32 %tx, %tid.x; mov.u32 %cx, %ctaid.x; mov.u32 %nx, %ntid.x;
  mad.lo.u32 %gid, %cx, %nx, %tx;
  mul.wide.u32 %off, %gid, 4;
  add.s64 %ptr, %base, %off;
  st.global.f32 [%ptr], %c0;
  ret;
}
"""

cuda = C.WinDLL("nvcuda.dll")
def ck(code, what):
    if code != 0:
        s = C.c_char_p()
        cuda.cuGetErrorString(code, C.byref(s))
        raise RuntimeError(f"{what} failed: CUDA {code} {s.value.decode() if s.value else ''}")

dev = C.c_int(); ctx = C.c_void_p(); mod = C.c_void_p(); fn = C.c_void_p()
ck(cuda.cuInit(0), "cuInit")
ck(cuda.cuDeviceGet(C.byref(dev), 0), "cuDeviceGet")
name = C.create_string_buffer(128); cuda.cuDeviceGetName(name, 128, dev)
# SM count + clock (driver attributes: 16 = MULTIPROCESSOR_COUNT, 13 = CLOCK_RATE kHz)
sm = C.c_int(); clk = C.c_int(); cc_major=C.c_int(); cc_minor=C.c_int()
cuda.cuDeviceGetAttribute(C.byref(sm), 16, dev)
cuda.cuDeviceGetAttribute(C.byref(clk), 13, dev)
cuda.cuDeviceGetAttribute(C.byref(cc_major), 75, dev)
cuda.cuDeviceGetAttribute(C.byref(cc_minor), 76, dev)
ck(cuda.cuCtxCreate_v2(C.byref(ctx), 0, dev), "cuCtxCreate")
ck(cuda.cuModuleLoadData(C.byref(mod), PTX), "cuModuleLoadData")
ck(cuda.cuModuleGetFunction(C.byref(fn), mod, b"bench"), "cuModuleGetFunction")

BLOCKS = max(1, sm.value) * 16
THREADS = 128
WARPS = BLOCKS * (THREADS // 32)
ITERS = 2_000_000

out = C.c_ulonglong()
ck(cuda.cuMemAlloc_v2(C.byref(out), BLOCKS * THREADS * 4), "cuMemAlloc")

p_out = C.c_ulonglong(out.value); p_it = C.c_uint(ITERS)
params = (C.c_void_p * 2)(C.cast(C.byref(p_out), C.c_void_p), C.cast(C.byref(p_it), C.c_void_p))

start = C.c_void_p(); stop = C.c_void_p()
cuda.cuEventCreate(C.byref(start), 0); cuda.cuEventCreate(C.byref(stop), 0)

def run(iters):
    p_it.value = iters
    ck(cuda.cuEventRecord(start, None), "rec start")
    ck(cuda.cuLaunchKernel(fn, BLOCKS,1,1, THREADS,1,1, 0, None, params, None), "launch")
    ck(cuda.cuEventRecord(stop, None), "rec stop")
    ck(cuda.cuCtxSynchronize(), "sync")
    ms = C.c_float(); cuda.cuEventElapsedTime(C.byref(ms), start, stop)
    return ms.value / 1000.0

run(1000)  # warm up / JIT
best = min(run(ITERS) for _ in range(5))
flops_per_mma = 2 * 16 * 8 * 16
total = WARPS * ITERS * flops_per_mma
tflops = total / best / 1e12

print(f"GPU: {name.value.decode()}  cc={cc_major.value}.{cc_minor.value}  SMs={sm.value}  rated_clock={clk.value/1000:.0f}MHz (static, not live)")
print(f"warps={WARPS} iters/warp={ITERS} time={best*1000:.1f}ms")
print(f"FP16 tensor (f32 accumulate): {tflops:.1f} TFLOPS")
print()
print("Reference RTX 3070 Laptop (GA104, 40 SM) @ pinned 1500 MHz: ~28-29 locked, ~57 unlocked.")
print("  (Full boost ~1860 MHz: ~39 locked / ~73 unlocked.)")
print("VERDICT:", "UNLOCKED (near full rate)" if tflops > 50 else
                  "LOCKED / reverted (half rate)" if tflops < 45 else "borderline - rerun")
print("  (valid only at a pinned/known SM clock -- nvidia-smi -lgc 1500,1500 first; a low number at a low clock is NOT 'locked')")
