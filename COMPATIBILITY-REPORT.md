# Compatibility report: RTX 3070 Laptop GPU (10de:249d, GA104M) — Windows UEFI unlock, FP16 **+87%**

**TL;DR:** The FP/BF16 speed unlock works on a **MUXless Optimus laptop** (RTX 3070 Laptop, GA104) under **Windows 10**, applied pre‑boot from a UEFI image and held in Windows with a CUDA keep‑alive. Dense FP16 tensor throughput went from **38.8 → 72.6 TFLOPS (+87%, ~2×)**; the FP32 control is unchanged. No ready port supported this configuration, so the upstream Windows UEFI port was adapted for it.

## Hardware
| | |
|---|---|
| Laptop | GIGABYTE A5 X1 (SKU RC45AX), INSYDE BIOS 1.07.FB08 |
| dGPU | NVIDIA GeForce RTX 3070 Laptop GPU, `10de:249d`, subsystem `1558:50f2` (Clevo board), GA104, 8 GB, VBIOS 94.04.42.00.04 |
| iGPU | AMD Radeon (Ryzen 9 5900HX, Cezanne) — drives the only display (**MUXless Optimus**; the dGPU drives no display) |
| OS / driver | Windows 10 Pro 22H2 (19045), NVIDIA 621.01 |
| Secure Boot / BitLocker | off / off |

## Why the stock port refused it
- The dGPU boots with **PCI COMMAND = 0x0000** (memory decode off) pre‑OS — normal for a MUXless laptop — so the standard config/BAR/PROM checks fail until memory is reversibly enabled.
- The dGPU **drives no display**, so the port's exact AMD‑GOP display‑topology check does not apply.
- `10de:249d` is not in the reviewed GA104 identity list.

## Method (adapted from the upstream Windows UEFI port)
Built from [impacifist/Windows-GPU-UNLOCK](https://github.com/impacifist/Windows-GPU-UNLOCK) (which vendors the Linux [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock) 610 transaction). Changes for this machine:
1. New `GU_PROFILE_A5X1_3070M` machine profile from a read‑only probe capture (ID/subsystem/BAR0/chip/VRAM/PROM sha256/cold selectors).
2. Added `0x249d10de` (0x2000 MiB) to the GA104 family allow‑list.
3. **Reversibly enable memory decode** (`PciIo->Attributes` MEMORY) before the config check; the saved config carries it across the FLR, restored afterwards. Only the memory bit is touched; bus‑master is managed by the transaction.
4. **DisplayCheck** rewritten for the no‑display case: verify no GOP routes to the dGPU (so the FLR cannot disturb the AMD‑driven console).
5. Relaxed the USB boot‑path check (this firmware's USB device path lacks a standard USB node).
6. Firmware assets generated for GA102/610.43.03 (incl. the V67 payload) and loaded from the USB.

The transaction itself (FWSEC/Booter V67, PLM open, write `SS0=0x88888888`/`SS1=0x8`, PCIe FLR, post‑FLR verify) is the unmodified upstream core. Manual `U` confirmation; all cold‑state and post‑FLR fail‑safes retained.

## Results
Laptop boost clocks wander run‑to‑run, so the clean A/B is at a **pinned SM clock** (`nvidia-smi -lgc 1500,1500`). Two independent tools agree to the decimal.

**Pinned 1500 MHz, dense 8192³ GEMM, FP32 accumulation (reduced‑precision reductions off):**
| Precision | Locked (half‑rate) | Unlocked | Δ |
|---|---:|---:|---:|
| **FP16** | ~28–29 TFLOPS | **57.1 TFLOPS** | **~2× (+95%)** |
| **BF16** | ~28 TFLOPS | **56.0 TFLOPS** | ~2× |
| **TF32** | ~14 TFLOPS | **28.3 TFLOPS** | ~2× |
| FP32 (control) | 11.2 TFLOPS | 11.2 TFLOPS | ~0% |

- **PyTorch 2.6 + cuBLAS** and a self‑contained **raw `mma.sync.m16n8k16`** CUDA‑Driver‑API microbenchmark both read **57.1 TFLOPS FP16 at 1500 MHz** unlocked.
- At full boost (~1860 MHz) the raw tensor peak is **38.8 → 72.6 TFLOPS (+87%)**.
- The flat FP32 control confirms the gain is the unlocked tensor issue rate, not clocks or power.

> Note: on a laptop, don't compare raw TFLOPS across separate runs — the boost clock varies, which masks the effect. Pin the clock, or compare only within one run. A low reading at low clock is not "locked"; verify at a fixed clock.

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

## Persistence on Windows (the key finding)
A pre‑boot unlock is **reset after Windows boots** — not by a driver re‑latch, but by **RTD3 idle power‑down** of the dGPU. Measuring after login always read 38.8 (locked). Holding it:
- Re‑run the UEFI unlock, boot Windows, and start a **CUDA keep‑alive at logon** (an auto‑started script that touches the dGPU every 100 ms so it never idle‑powers‑down). The keep‑alive must grab the card before the first RTD3 cycle — a manual post‑login run is too late; an at‑logon autostart catches it.
- With the keep‑alive running, FP16 holds at **72.6 TFLOPS** indefinitely.

So on this GA104M laptop the revert is RTD3, and a keep‑alive is sufficient (matching the Windows results reported for other Ampere laptops). The unlock is **volatile**: a full power‑off loses it (re‑run the USB next boot).

## Reproduce
1. Read‑only probe → capture the card's identity/BAR0/PROM/cold selectors.
2. Build the unlock EFI with the machine profile above; put it as `\EFI\BOOT\BOOTX64.EFI` + firmware in `\RTX3090-UNLOCK\ASSETS\` on a FAT32 USB.
3. Secure Boot off → boot the USB → press `U`.
4. Boot Windows with an at‑logon CUDA keep‑alive; measure FP16 tensor TFLOPS.

## Credits & license
Based on GPL‑2.0 work by **Zagitta/gpu-unlock** and **impacifist/Windows-GPU-UNLOCK**. This adaptation inherits GPL‑2.0.

## Caveats
Experimental; one laptop, untested elsewhere. Volatile (per power‑cycle). Affects **FP16/BF16/TF32 tensor only** — games, FP32 shading and quantized/INT inference are unchanged. No VBIOS reflash; all changes reset on power‑off. Use at your own risk.
