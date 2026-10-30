#!/usr/bin/env python3
# Recognized dense GEMM benchmark (gpu-unlock report format): 8192^3, FP16/BF16/TF32
# with FP32 accumulation (reduced-precision reductions OFF), plus an FP32 control.
# Sustained back-to-back matmuls hold boost clocks (per-iter sync lets the GPU idle
# down and under-reports). Run UNLOCKED (keep-alive holding) and LOCKED (plain boot).
import torch, time

assert torch.cuda.is_available(), "CUDA GPU not available to PyTorch"
dev = "cuda"
torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False
torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction = False
N = 8192

def bench(dtype, tf32=False, seconds=5.0):
    torch.backends.cuda.matmul.allow_tf32 = tf32
    a = torch.randn(N, N, device=dev, dtype=dtype)
    b = torch.randn(N, N, device=dev, dtype=dtype)
    for _ in range(50):          # warm up / spin clocks to boost
        c = a @ b
    torch.cuda.synchronize()
    iters = 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        for _ in range(20):
            c = a @ b
        torch.cuda.synchronize()
        iters += 20
    dt = time.perf_counter() - t0
    return (2.0 * N**3) * iters / dt / 1e12

print(f"GPU: {torch.cuda.get_device_name(0)}")
print(f"torch {torch.__version__}  CUDA {torch.version.cuda}  N={N} (sustained)")
print(f"FP16  (FP32 acc): {bench(torch.float16):6.1f} TFLOPS")
print(f"BF16  (FP32 acc): {bench(torch.bfloat16):6.1f} TFLOPS")
print(f"TF32           : {bench(torch.float32, tf32=True):6.1f} TFLOPS")
print(f"FP32  (control): {bench(torch.float32, tf32=False):6.1f} TFLOPS")
