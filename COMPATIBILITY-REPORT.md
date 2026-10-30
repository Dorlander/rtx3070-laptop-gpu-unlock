# Compatibility report: RTX 3070 Laptop GPU (10de:249d, GA104M) — Windows UEFI unlock, FP16 **~1.8×**

**TL;DR:** The FP/BF16 speed unlock works on a **MUXless Optimus laptop** (RTX 3070 Laptop, GA104) under **Windows 10**, applied pre-boot from a UEFI image and held in Windows with a CUDA keep-alive. At a pinned 1500 MHz SM clock, dense FP16 tensor throughput is **53.8 TFLOPS unlocked vs 30.0 locked — a measured ~1.8× A/B** (both states captured on the same machine, two tools agreeing, files in `evidence/`); the FP32 control is unchanged. No ready port supported this configuration, so the upstream Windows UEFI port was adapted for it.

## Hardware
| | |
|---|---|
| Laptop | GIGABYTE A5 X1 (SKU RC45AX), INSYDE BIOS 1.07.FB08 |
| dGPU | NVIDIA GeForce RTX 3070 Laptop GPU, `10de:249d`, subsystem `1558:50f2` (Clevo board), GA104, 8 GB, VBIOS 94.04.42.00.04 |
| iGPU | AMD Radeon (Ryzen 9 5900HX, Cezanne) — drives the only display (**MUXless Optimus**; the dGPU drives no display) |
| OS / driver | Windows 10 Pro 22H2 (19045), NVIDIA 621.01 |
| Secure Boot / BitLocker | off / off |

## Why the stock port refused it
- The dGPU boots with **PCI COMMAND = 0x0000** (memory decode off) pre-OS — normal for a MUXless laptop — so the standard config/BAR/PROM checks fail until memory is reversibly enabled.
- The dGPU **drives no display**, so the port's exact AMD-GOP display-topology check does not apply.
- `10de:249d` is not in the reviewed GA104 identity list.

## Method (adapted from the upstream Windows UEFI port)
Built from [impacifist/Windows-GPU-UNLOCK](https://github.com/impacifist/Windows-GPU-UNLOCK) (which vendors the Linux [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock) 610 transaction). Changes for this machine (`patches/a5x1-adaptation.patch`):
1. New `GU_PROFILE_A5X1_3070M` machine profile from a read-only probe capture (ID/subsystem/BAR0/chip/VRAM/PROM sha256/cold selectors).
2. Added `0x249d10de` (0x2000 MiB) to the GA104 family allow-list.
3. **Reversibly enable memory decode** (`PciIo->Attributes` MEMORY) before the config check; the saved config carries it across the FLR, restored afterwards. Only the memory bit is touched; bus-master is managed by the transaction.
4. **DisplayCheck** rewritten for the no-display case: verify no GOP routes to the dGPU (so the FLR cannot disturb the AMD-driven console).
5. Relaxed the USB boot-path check (this firmware's USB device path lacks a standard USB node).
6. Firmware assets generated for GA102/610.43.03 (incl. the V67 payload) and loaded from the USB.

The transaction itself (FWSEC/Booter V67, PLM open, write `SS0=0x88888888`/`SS1=0x8`, PCIe FLR, post-FLR verify) is the unmodified upstream core. Manual `U` confirmation; all cold-state and post-FLR fail-safes retained. Full step-by-step build/run is in the [README](README.md#reproduce).

## Results
Laptop boost clocks wander run-to-run, so the clean A/B is at a **pinned SM clock** (`nvidia-smi -lgc 1500,1500`). Both states below are **measured captures** on the same machine in one session (files in `evidence/`), each read by two independent tools.

**Pinned 1500 MHz, dense 8192³ GEMM, FP32 accumulation (reduced-precision reductions off):**
| Precision | Locked @1500 (measured) | Unlocked @1500 (measured) | Δ |
|---|---:|---:|---:|
| **FP16** | 30.0 TFLOPS | **53.8 TFLOPS** | **~1.8×** |
| **BF16** | 30.2 TFLOPS | **52.9 TFLOPS** | ~1.75× |
| **TF32** | 14.9 TFLOPS | **26.7 TFLOPS** | ~1.8× |
| FP32 (control) | 11.2 TFLOPS | 10.5 TFLOPS | ~1.0× |

- Both halves are real captures — [`evidence/bench-unlocked-1500.txt`](evidence/bench-unlocked-1500.txt) and [`evidence/bench-locked-1500.txt`](evidence/bench-locked-1500.txt) — each with the `nvidia-smi` clock readback proving the SM clock held at 1500 MHz, and **PyTorch cuBLAS and the raw `mma.sync.m16n8k16` microbench agreeing to the decimal** (FP16 unlocked 53.8/53.8; locked 30.0/30.3).
- The **locked** half was captured when the dGPU idled between runs and **RTD3 reverted the unlock** — the same effect the keep-alive prevents — so it is a genuine locked measurement at the pinned clock, not an inferred half-rate.
- FP16/BF16/TF32 each land at ~1.8× (approaching the 2× architectural maximum). The **FP32 control is flat** (11.2 / 10.5, within run noise); FP32 doesn't use the gated path, so its flatness confirms the gain is tensor **issue rate**, not clocks or power.

**Full-boost observation (secondary, not a controlled A/B):** at stock clocks (~1860 MHz) the raw FP16 tensor peak read **38.8 TFLOPS locked** and **72.6 TFLOPS unlocked** — two separate readings at unpinned, wandering boost clocks, consistent with the pinned A/B but not controlled.

> Note: on a laptop, don't compare raw TFLOPS across separate runs — the boost clock varies, which masks the effect. Pin the clock, or compare only within one run. A low reading at low clock is not "locked".

### Transaction evidence (UEFI `REPORT.TXT`, clean run)
```
cold state: chip=0xb74000a1 ... WPR2_HI=0 SS0=0x40364047 SS1=0x6
A5X1 enable memory decode: supported=0xe718 status=0
A5X1 no-display check: gops=2 dgpu_drives_display=0
pre-FLR selectors: ss0=0x88888888 expected=0x88888888 ss1=0x8 expected=0x8
PCIe FLR returned: result=0
post-FLR SEC2 reset released, GSP halted, BME=0 ... SS0=88888888 SS1=00000008
transaction result=0 ... fault=0 retained=0 FLR=1
FINAL status=0 stage=transaction ... clean=1
```
This log proves the **UEFI transaction completed cleanly** (it contains no throughput numbers — a pre-boot app can't benchmark; the TFLOPS come from the Windows scripts above). The full log (`evidence/unlock-REPORT.TXT`) also carries upstream **"RTX3090 / 24GB"** and **"hardware untested"** banners inherited from the reused `-DGU_EXPERIMENTAL_3090` build mode; the same log proves the real card is the 8 GB RTX 3070 Laptop (`config[00]=249d10de`, `memory=0x2000`). See [evidence/README.md](evidence/README.md).

## Persistence on Windows (the key finding)
A pre-boot unlock is **reset after Windows boots** — not by a driver re-latch, but by **RTD3 idle power-down** of the dGPU. Measuring after login always read 38.8 (locked, full boost). Holding it:
- Re-run the UEFI unlock, boot Windows, and start a **CUDA keep-alive at logon** (an auto-started script that touches the dGPU every 100 ms so it never idle-powers-down). The keep-alive must grab the card before the first RTD3 cycle — a manual post-login run is too late; an at-logon autostart catches it.
- With the keep-alive running, the unlocked tensor rate holds indefinitely.

So on this GA104M laptop the revert is RTD3, and a keep-alive is sufficient (matching the Windows results reported for other Ampere laptops). The unlock is **volatile**: a full power-off loses it (re-run the USB next boot).

## Reproduce
Summarized here; full commands in the [README](README.md#reproduce).
1. Clone impacifist/Windows-GPU-UNLOCK at commit `1f8776e` and `git apply patches/a5x1-adaptation.patch`.
2. Read-only probe → capture the card's identity/BAR0/PROM/cold selectors (skip for this exact card).
3. Generate the 5 GA102/610.43.03 firmware assets; put the unlock EFI as `\EFI\BOOT\BOOTX64.EFI` + firmware in `\RTX3090-UNLOCK\ASSETS\` on a FAT32 USB.
4. Secure Boot off → boot the USB → press `U`.
5. Boot Windows with an at-logon CUDA keep-alive; pin the clock and measure FP16 tensor TFLOPS.

## Credits & license
Based on GPL-2.0 work by **Zagitta/gpu-unlock** and **impacifist/Windows-GPU-UNLOCK**. This adaptation inherits GPL-2.0.

## Caveats
Experimental; one laptop, untested elsewhere. Volatile (per power-cycle). Affects **FP16/BF16/TF32 tensor only** — games, FP32 shading and quantized/INT inference are unchanged. No VBIOS reflash; all changes reset on power-off. Use at your own risk.
