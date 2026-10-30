# RTX 3070 Laptop (10de:249d, GA104M) — Windows GPU tensor unlock

Adapting the [gpu-unlock](https://github.com/Zagitta/gpu-unlock) FP/BF16 speed unlock to a **MUXless Optimus laptop** running **Windows 10**, where no existing port supported the configuration. Dense FP16/BF16 tensor throughput **roughly doubles**; verified with PyTorch cuBLAS and a raw `mma.sync` microbenchmark.

> **Status:** works and is reproducible on this exact machine. Experimental, one unit, GPL‑2.0. The unlock is **volatile** (per power‑cycle) and must be held with a CUDA keep‑alive on Windows. See [caveats](#caveats).

## Result

At a **pinned 1500 MHz** SM clock (`nvidia-smi -lgc 1500,1500`), dense 8192³ GEMM, FP32 accumulation — two independent tools agree:

| Precision | Locked (half‑rate) | **Unlocked** | Δ |
|---|---:|---:|---:|
| **FP16** | ~28–29 TFLOPS | **57.1 TFLOPS** | **~2×** |
| **BF16** | ~28 TFLOPS | **56.0 TFLOPS** | ~2× |
| **TF32** | ~14 TFLOPS | **28.3 TFLOPS** | ~2× |
| FP32 (control) | 11.2 | 11.2 | ~0% |

PyTorch 2.6 + cuBLAS **and** a self‑contained `mma.sync.m16n8k16` CUDA‑Driver‑API microbenchmark both read **57.1 TFLOPS FP16 at 1500 MHz** unlocked. At full boost (~1860 MHz) the raw tensor peak is **38.8 → 72.6 TFLOPS (+87%)**. The flat FP32 control proves the gain is the unlocked tensor **issue rate**, not clocks or power.

> On a laptop, never compare raw TFLOPS across separate runs — the boost clock wanders and masks the effect. Pin the clock, or compare within one run. A low number at a low clock is **not** "locked".

## Hardware

| | |
|---|---|
| Laptop | GIGABYTE A5 X1 (RC45AX), INSYDE BIOS 1.07.FB08 |
| dGPU | RTX 3070 Laptop GPU, `10de:249d`, subsystem `1558:50f2` (Clevo board), GA104, 8 GB, VBIOS 94.04.42.00.04 |
| iGPU | AMD Radeon (Ryzen 9 5900HX) — drives the only display (**MUXless Optimus**; the dGPU drives no display) |
| OS / driver | Windows 10 Pro 22H2 (19045), NVIDIA 621.01, Secure Boot **off** |

## Why the stock port refused it

- The dGPU boots **PCI COMMAND = 0x0000** (memory decode off) pre‑OS — normal for a MUXless laptop — so the config/BAR/PROM checks fail until memory is reversibly enabled.
- The dGPU **drives no display**, so the port's exact AMD‑GOP display‑topology check doesn't apply.
- `10de:249d` is not in the reviewed GA104 identity list.

## What's in this repo

```
patches/a5x1-adaptation.patch   my diff vs impacifist/Windows-GPU-UNLOCK (unlock + read-only probe)
patches/platform-config.h       zero-GUID config for the read-only probe build
scripts/tensor_bench.py          FP16 tensor-core peak microbench (CUDA Driver API, no toolkit/torch)
scripts/tensor_bench_loop.py     live monitor + keep-alive (heavy)
scripts/gpu_keepalive_light.py   light keep-alive (holds the unlock, leaves the GPU free)
scripts/gpu-unlock-keepalive.bat at-logon autostart for the keep-alive
scripts/torch_gemm.py            recognized 8192^3 GEMM A/B (FP16/BF16/TF32), pin the clock first
scripts/gsp_from_run.py          GSP firmware extractor (Windows, zstandard; no zstd binary)
evidence/unlock-REPORT.TXT       the UEFI unlock transaction log (clean success)
COMPATIBILITY-REPORT.md          the formal compatibility report
```

**Not included** (proprietary NVIDIA — generate them yourself, see below): the 5 firmware assets, the card's VBIOS/PROM dump, and any built EFI binary.

## How it works (the adaptation)

Built from [impacifist/Windows-GPU-UNLOCK](https://github.com/impacifist/Windows-GPU-UNLOCK) (which vendors the Linux [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock) 610 transaction). The transaction core (FWSEC/Booter V67, PLM open, write `SS0=0x88888888`/`SS1=0x8`, PCIe FLR, post‑FLR verify) is **unmodified upstream**. My changes (`patches/a5x1-adaptation.patch`):

1. New `GU_PROFILE_A5X1_3070M` machine profile from a read‑only probe capture (identity/subsystem/BAR0/chip/VRAM/PROM sha256/cold selectors).
2. Added `0x249d10de` (0x2000 MiB) to the GA104 family allow‑list (`gpu-family.h`).
3. **Reversibly enable memory decode** (`PciIo->Attributes` MEMORY only) before the config check; the saved config carries it across the FLR and is restored afterward (`app.c` FindTarget).
4. **DisplayCheck** rewritten for no‑display: verify no GOP routes to the dGPU, so the FLR can't disturb the AMD console (`app.c`).
5. Relaxed the USB boot‑path check (this firmware's USB device path lacks a standard USB node) (`app_io.c`).

All cold‑state / post‑FLR fail‑safes and the manual `U` confirmation are retained.

## Reproduce (summary)

1. **Probe (read‑only):** build the probe (`patches/` + `GU_PROBE_GENERIC`), boot it from a FAT32 USB, capture `GPUDIAG00.TXT` + `PROM.BIN` → your card's identity, BAR0, chip, cold selectors, PROM sha256.
2. **Profile:** fill `GU_PROFILE_A5X1_3070M` in `machine-profile.h` with your capture (if your card differs).
3. **Firmware:** generate the 5 GA102/610.43.03 assets with the upstream pinned tool and verify against `internal-boot/unlock/assets.json`:
   ```sh
   git clone https://github.com/Zagitta/gpu-unlock && cd gpu-unlock
   git checkout --detach 0ebdb1c6308b6a2072be5bf04513472942541956
   make inputs firmware PYTHON=python3.14           # booter_load_ga102, v67-ga102-610.43.03, gsp_ga10x, gsp_boot_ga102, gsp_boot_desc_ga102
   ```
   (On Windows without WSL, `scripts/gsp_from_run.py` extracts `gsp_ga10x.bin`; the rest come from `firmware/extract_boot_assets.py` and `firmware/generate_v67.py`.)
4. **Build the unlock EFI** (clang + lld‑link, against impacifist's vendored EDK2 headers):
   ```
   clang -target x86_64-pc-windows-msvc -std=c11 -ffreestanding -fno-builtin -fno-stack-protector \
     -mno-red-zone -fshort-wchar -Os -Wall -Wextra -Werror -Wno-unused-parameter -Wno-unused-function \
     -D__KERNEL__ -DGU_UEFI_PORT -DGU_TARGET_PCI_ID=0x249d10deU -DGU_PROFILE_A5X1_3070M \
     -DGU_EXPERIMENTAL_3090 -DGU_ENTRY_LATCHED_SS1_FULL \
     -I compat -I ../../deps/edk2/MdePkg/Include -I ../../deps/edk2/MdePkg/Include/X64 -c <each source>.c
   lld-link /nologo /nodefaultlib /subsystem:efi_application /entry:efi_main /machine:x64 ... /out:BOOTX64.EFI
   ```
   Sources: `app app_io ownership format runtime sha256 checks port compat vendor/unlock_610 vendor/prep_610 vendor/layout_610 vendor/vbios_610 vendor/gfw_eval`.
5. **USB:** FAT32, `\EFI\BOOT\BOOTX64.EFI` + the 5 firmware files in `\RTX3090-UNLOCK\ASSETS\`. Keep `\RTX3090-UNLOCK\` writable (the app logs `RUNxx\REPORT.TXT`).
6. **Run:** Secure Boot off → boot the USB → press **U** → Windows boots.
7. **Hold it on Windows:** auto‑start `scripts/gpu_keepalive_light.py` at logon (`scripts/gpu-unlock-keepalive.bat` in the Startup folder). It touches the dGPU every 100 ms so RTD3 never power‑cycles it (which would reset the unlock). It must grab the card **before** the first idle — an at‑logon autostart does; a manual run after login is too late.
8. **Verify:** `nvidia-smi -lgc 1500,1500` then `py tensor_bench.py` or `torch_gemm.py`; `nvidia-smi -rgc` after.

## Caveats

- **Volatile:** a full power‑off loses the unlock; re‑run the USB each boot.
- **Windows persistence** needs the keep‑alive running (the revert is RTD3 idle power‑down, not a driver re‑latch).
- Affects **FP16/BF16/TF32 tensor only** — games, FP32 shading and quantized/INT inference are unchanged. Normal/gaming benchmarks show **nothing**.
- One laptop, **untested elsewhere**. No VBIOS reflash; everything resets on power‑off. Experimental — **use at your own risk**.

## Credits & license

Based on GPL‑2.0 work by **[Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock)** and **[impacifist/Windows-GPU-UNLOCK](https://github.com/impacifist/Windows-GPU-UNLOCK)**. This adaptation is **GPL‑2.0**. NVIDIA firmware and VBIOS are the property of NVIDIA and are **not redistributed** here.
