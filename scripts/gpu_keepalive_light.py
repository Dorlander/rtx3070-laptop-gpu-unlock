#!/usr/bin/env python3
# LIGHT keep-alive: holds the dGPU awake with negligible load so the UEFI-applied
# unlock is not lost to RTD3 power-down, while leaving the GPU free for real work.
# A tiny kernel every 100 ms resets the idle timer; every 60 s it prints the FP16
# tensor rate as a health check (~57-73 = unlocked, ~28-39 = reset; scales with SM clock). Ctrl+C / close to stop.
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
def ck(c, w):
    if c:
        s=C.c_char_p(); cuda.cuGetErrorString(c, C.byref(s))
        raise RuntimeError(f"{w}: CUDA {c} {s.value.decode() if s.value else ''}")
dev=C.c_int(); ctx=C.c_void_p(); mod=C.c_void_p(); fn=C.c_void_p()
ck(cuda.cuInit(0),"init"); ck(cuda.cuDeviceGet(C.byref(dev),0),"dev")
sm=C.c_int(); cuda.cuDeviceGetAttribute(C.byref(sm),16,dev)
ck(cuda.cuCtxCreate_v2(C.byref(ctx),0,dev),"ctx")
ck(cuda.cuModuleLoadData(C.byref(mod),PTX),"load"); ck(cuda.cuModuleGetFunction(C.byref(fn),mod,b"bench"),"fn")
out=C.c_ulonglong(); ck(cuda.cuMemAlloc_v2(C.byref(out), max(1,sm.value)*16*128*4),"mem")
p_out=C.c_ulonglong(out.value); p_it=C.c_uint(0)
params=(C.c_void_p*2)(C.cast(C.byref(p_out),C.c_void_p),C.cast(C.byref(p_it),C.c_void_p))
start=C.c_void_p(); stop=C.c_void_p(); cuda.cuEventCreate(C.byref(start),0); cuda.cuEventCreate(C.byref(stop),0)

def nudge():            # tiny: a handful of warps, ~instant -> just resets idle timer
    p_it.value=1000
    ck(cuda.cuLaunchKernel(fn, 8,1,1, 64,1,1, 0, None, params, None),"nudge")
    cuda.cuCtxSynchronize()

def measure():          # brief full-rate sample for the health check
    FULL=2_000_000; BLK=max(1,sm.value)*16; WARPS=BLK*4
    p_it.value=FULL; cuda.cuEventRecord(start,None)
    cuda.cuLaunchKernel(fn, BLK,1,1, 128,1,1, 0, None, params, None)
    cuda.cuEventRecord(stop,None); cuda.cuCtxSynchronize()
    ms=C.c_float(); cuda.cuEventElapsedTime(C.byref(ms),start,stop)
    return WARPS*FULL*2*16*8*16/(ms.value/1000.0)/1e12

nudge()
tf=measure()
print(f"Light keep-alive active (SMs={sm.value}). The dGPU stays awake, so the unlock holds.")
print(f"Start rate: {tf:.1f} TFLOPS  -> {'UNLOCKED' if tf>50 else 'LOW - if the card idled/throttled, pin 1500 MHz to confirm'}")
print("Leave this running while you use the GPU. Health check every 60 s. Ctrl+C to stop.")
last=time.time()
try:
    while True:
        nudge(); time.sleep(0.1)
        if time.time()-last>=60:
            tf=measure(); print(f"{time.strftime('%H:%M:%S')}  {tf:5.1f} TFLOPS  {'UNLOCKED' if tf>50 else 'LOW?'}")
            last=time.time()
except KeyboardInterrupt:
    print("keep-alive stopped")
