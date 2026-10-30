#!/usr/bin/env python3
# Keep-alive + monitor: holds ONE CUDA context (keeps the dGPU awake, defeating
# RTD3 power-down) and re-measures FP16 tensor TFLOPS every ~2 s, printing a line
# each time. Run it the INSTANT Windows reaches the desktop after a USB unlock
# boot. If the unlock survived, you'll see ~60-70; if Windows reset it, ~38.
# Ctrl+C to stop.  Works on Python 3.14 (CUDA Driver API via nvcuda.dll).
import ctypes as C, time

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
def ck(c, what):
    if c:
        s=C.c_char_p(); cuda.cuGetErrorString(c, C.byref(s))
        raise RuntimeError(f"{what}: CUDA {c} {s.value.decode() if s.value else ''}")
dev=C.c_int(); ctx=C.c_void_p(); mod=C.c_void_p(); fn=C.c_void_p()
ck(cuda.cuInit(0),"init"); ck(cuda.cuDeviceGet(C.byref(dev),0),"dev")
sm=C.c_int(); cuda.cuDeviceGetAttribute(C.byref(sm),16,dev)
ck(cuda.cuCtxCreate_v2(C.byref(ctx),0,dev),"ctx")
ck(cuda.cuModuleLoadData(C.byref(mod),PTX),"load"); ck(cuda.cuModuleGetFunction(C.byref(fn),mod,b"bench"),"fn")
BLOCKS=max(1,sm.value)*16; THREADS=128; WARPS=BLOCKS*(THREADS//32); ITERS=2_000_000
out=C.c_ulonglong(); ck(cuda.cuMemAlloc_v2(C.byref(out),BLOCKS*THREADS*4),"mem")
p_out=C.c_ulonglong(out.value); p_it=C.c_uint(ITERS)
params=(C.c_void_p*2)(C.cast(C.byref(p_out),C.c_void_p),C.cast(C.byref(p_it),C.c_void_p))
start=C.c_void_p(); stop=C.c_void_p(); cuda.cuEventCreate(C.byref(start),0); cuda.cuEventCreate(C.byref(stop),0)
def run(it):
    p_it.value=it; cuda.cuEventRecord(start,None)
    ck(cuda.cuLaunchKernel(fn,BLOCKS,1,1,THREADS,1,1,0,None,params,None),"launch")
    cuda.cuEventRecord(stop,None); ck(cuda.cuCtxSynchronize(),"sync")
    ms=C.c_float(); cuda.cuEventElapsedTime(C.byref(ms),start,stop); return ms.value/1000.0
run(1000)
print(f"SMs={sm.value}  warps={WARPS}. Monitoring FP16 tensor rate (Ctrl+C to stop)...")
print("Locked ~38 TFLOPS | Unlocked ~60-70 TFLOPS")
flops=WARPS*ITERS*2*16*8*16
try:
    while True:
        t=min(run(ITERS) for _ in range(3)); tf=flops/t/1e12
        tag="UNLOCKED" if tf>50 else ("LOCKED" if tf<45 else "borderline")
        print(f"{time.strftime('%H:%M:%S')}  {tf:5.1f} TFLOPS  {tag}")
except KeyboardInterrupt:
    print("stopped")
