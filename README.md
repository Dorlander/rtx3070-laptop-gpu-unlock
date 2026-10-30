# RTX 3070 Laptop (10de:249d, GA104M) — Windows GPU tensor unlock

Adapting the [gpu-unlock](https://github.com/Zagitta/gpu-unlock) FP/BF16 speed unlock to a **MUXless Optimus laptop** running **Windows 10**, where no existing port supported the configuration. Dense FP16/BF16 tensor throughput **roughly doubles**; the unlocked rate is measured with PyTorch cuBLAS and a raw `mma.sync` microbenchmark.

> **Status:** works and is reproducible on this exact machine. Experimental, one unit, GPL-2.0. The unlock is **volatile** (per power-cycle) and must be held with a CUDA keep-alive on Windows. See [caveats](#caveats).

## Result

At a **pinned 1500 MHz** SM clock (`nvidia-smi -lgc 1500,1500`), dense 8192³ GEMM, FP32 accumulation:

| Precision | Locked @1500 (half-rate, *inferred*) | **Unlocked @1500 (measured)** | Δ |
|---|---:|---:|---:|
| **FP16** | ~28–29 TFLOPS | **57.1 TFLOPS** | **~2×** |
| **BF16** | ~28 TFLOPS | **56.0 TFLOPS** | ~2× |
| **TF32** | ~14 TFLOPS | **28.3 TFLOPS** | ~2× |
| FP32 (control, one run) | 11.2 | 11.2 | ~0% |

The **unlocked** column is measured: PyTorch 2.6 + cuBLAS and a self-contained `mma.sync.m16n8k16` CUDA-Driver-API microbenchmark agree on it (both **57.1 TFLOPS FP16 at a pinned 1500 MHz**). The **locked** column is the architectural half-rate reference — Ampere runs FP16/BF16/TF32-with-FP32-accumulate at half throughput until the unlock, so it is exactly half the measured unlocked figure, **not a separate capture**. The one *directly measured* locked figure is **38.8 TFLOPS at full boost**, where unlocked reads **72.6** — that 38.8 → 72.6 pair is two separate readings at unpinned, wandering boost clocks: consistent with ~2×, but not a controlled A/B (the pinned 1500 MHz result above is the clean one). FP32 is unaffected by the unlock and was measured once (shown in both columns), so it stays flat — evidence the gain is tensor **issue rate**, not clocks or power.

> On a laptop, never compare raw TFLOPS across separate runs — the boost clock wanders and masks the effect. Pin the clock, or compare within one run. A low number at a low clock is **not** "locked".

## Hardware

| | |
|---|---|
| Laptop | GIGABYTE A5 X1 (RC45AX), INSYDE BIOS 1.07.FB08 |
| dGPU | RTX 3070 Laptop GPU, `10de:249d`, subsystem `1558:50f2` (Clevo board), GA104, 8 GB, VBIOS 94.04.42.00.04 |
| iGPU | AMD Radeon (Ryzen 9 5900HX) — drives the only display (**MUXless Optimus**; the dGPU drives no display) |
| OS / driver | Windows 10 Pro 22H2 (19045), NVIDIA 621.01, Secure Boot **off** |

## Why the stock port refused it

- The dGPU boots **PCI COMMAND = 0x0000** (memory decode off) pre-OS — normal for a MUXless laptop — so the config/BAR/PROM checks fail until memory is reversibly enabled.
- The dGPU **drives no display**, so the port's exact AMD-GOP display-topology check doesn't apply.
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
evidence/unlock-REPORT.TXT       the UEFI transaction log — proves the transaction, NOT throughput
evidence/README.md               how to read the log (incl. the inherited "3090" labels)
COMPATIBILITY-REPORT.md          the formal compatibility report
```

**Not included** (proprietary NVIDIA — generate them yourself, see Reproduce): the 5 firmware assets, the card's VBIOS/PROM dump, and any built EFI binary.

## How it works (the adaptation)

Built from [impacifist/Windows-GPU-UNLOCK](https://github.com/impacifist/Windows-GPU-UNLOCK) (which vendors the Linux [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock) 610 transaction). The transaction core (FWSEC/Booter V67, PLM open, write `SS0=0x88888888`/`SS1=0x8`, PCIe FLR, post-FLR verify) is **unmodified upstream**. My changes (`patches/a5x1-adaptation.patch`, 6 files):

1. New `GU_PROFILE_A5X1_3070M` machine profile (`unlock/machine-profile.h`) from a read-only probe capture (identity/subsystem/BAR0/chip/VRAM/PROM sha256/cold selectors).
2. Added `0x249d10de` (0x2000 MiB) to the GA104 family allow-list (`unlock/gpu-family.h`).
3. **Reversibly enable memory decode** (`PciIo->Attributes` MEMORY only) before the config check; the saved config carries it across the FLR and is restored afterward (`unlock/app.c` FindTarget).
4. **DisplayCheck** rewritten for no-display: verify no GOP routes to the dGPU, so the FLR can't disturb the AMD console (`unlock/app.c`).
5. Relaxed the USB boot-path check (this firmware's USB device path lacks a standard USB node) (`unlock/app_io.c`).
6. A read-only diagnostic **probe** (`boot/probe.c`, `boot/handoff.c`) used once to capture this card's constants — it only reads and writes its capture to the USB.

All cold-state / post-FLR fail-safes and the manual `U` confirmation are retained.

## Reproduce

Everything below runs against **impacifist/Windows-GPU-UNLOCK with this repo's patch applied** — this repo ships only the patch and the scripts, not the full source tree.

**0. Get the source and apply the patch.** The patch was generated against impacifist commit `1f8776e`. That tree vendors EDK2 at `deps/edk2`.
```sh
git clone https://github.com/impacifist/Windows-GPU-UNLOCK && cd Windows-GPU-UNLOCK
git checkout --detach 1f8776ee9c6ee32f5920adaa4baabc9181379bd4
git apply /path/to/patches/a5x1-adaptation.patch
```

**1. Probe (read-only)** — only needed for a *different* card; for this exact card the profile is already filled. Build the diagnostic/probe EFI the way upstream `internal-boot/boot/build-diagnostic.ps1` does (sources `handoff.c diagnostic.c ../efi_runtime.c probe.c ../unlock/sha256.c`, from `internal-boot/boot/`), but add the macros this patch introduces: `-DGU_PROBE_GENERIC -DGU_DIAGNOSTIC_ONLY -DGU_PROBE_ENABLE_MEMORY -DGU_PROBE_PRESERVE_CAPTURE -DGU_USB_MEDIA`. `GU_PROBE_ENABLE_MEMORY` is **mandatory** on a MUXless card — it reversibly enables memory decode so the BAR/PROM reads work with `COMMAND=0x0000`; `GU_DIAGNOSTIC_ONLY` is what writes the root `\GPUDIAG00.TXT`. Copy `patches/platform-config.h` to `internal-boot/boot/platform-config.h` first. Boot from a FAT32 USB, read back `GPUDIAG00.TXT` (+ `PROM.BIN`) → your card's identity, BAR0, chip, cold selectors, PROM sha256.

**2. Profile:** copy `GU_PROFILE_A5X1_3070M` in `unlock/machine-profile.h` to a new block filled with your capture (skip for this exact card).

**3. Firmware (5 GA102 / 610.43.03 assets)** — NVIDIA proprietary; generate, don't download from here. On Linux/WSL the upstream tool does it all:
```sh
git clone https://github.com/Zagitta/gpu-unlock && cd gpu-unlock
git checkout --detach 0ebdb1c6308b6a2072be5bf04513472942541956
make inputs firmware PYTHON=python3        # needs GNU make + toolchain (WSL/MSYS on Windows)
```
On Windows without WSL you can still get `gsp_ga10x.bin` directly from the NVIDIA **610.43.03** Linux `.run` (e.g. `NVIDIA-Linux-x86_64-610.43.03.run` from NVIDIA's Unix driver archive):
```sh
pip install zstandard
py -3 scripts/gsp_from_run.py NVIDIA-Linux-x86_64-610.43.03.run <outdir>
```
The other four (`booter_load_ga102`, `v67-ga102-610.43.03`, `gsp_boot_ga102`, `gsp_boot_desc_ga102`) come from Zagitta's `firmware/extract_boot_assets.py` and `firmware/generate_v67.py`. Verify all five against `internal-boot/unlock/assets.json` **in the impacifist tree** (expected sizes/sha256 are also echoed in `evidence/unlock-REPORT.TXT`).

**4. Build the unlock EFI** (from `internal-boot/unlock/`, clang + lld-link against the vendored EDK2):
```sh
defs="-target x86_64-pc-windows-msvc -std=c11 -ffreestanding -fno-builtin -fno-stack-protector \
  -mno-red-zone -fshort-wchar -Os -Wall -Wextra -Werror -Wno-unused-parameter -Wno-unused-function \
  -D__KERNEL__ -DGU_UEFI_PORT -DGU_TARGET_PCI_ID=0x249d10deU -DGU_PROFILE_A5X1_3070M \
  -DGU_EXPERIMENTAL_3090 -DGU_ENTRY_LATCHED_SS1_FULL \
  -I compat -I ../../deps/edk2/MdePkg/Include -I ../../deps/edk2/MdePkg/Include/X64"
for s in app app_io ownership format runtime sha256 checks port compat \
         vendor/unlock_610 vendor/prep_610 vendor/layout_610 vendor/vbios_610 vendor/gfw_eval; do
  clang $defs -c "$s.c" -o "$(echo $s | tr / _).obj"; done
lld-link /nologo /nodefaultlib /subsystem:efi_application /entry:efi_main /machine:x64 \
  /base:0 /dynamicbase /nxcompat /timestamp:0 /opt:ref /opt:icf \
  app.obj app_io.obj ownership.obj format.obj runtime.obj sha256.obj checks.obj port.obj compat.obj \
  vendor_unlock_610.obj vendor_prep_610.obj vendor_layout_610.obj vendor_vbios_610.obj vendor_gfw_eval.obj \
  /out:BOOTX64.EFI
```
`app.c`/`app_io.c` are the two files this patch modifies; the rest are impacifist's unmodified sources under `internal-boot/unlock/` (`vendor/` beneath it). The `-DGU_EXPERIMENTAL_3090 -DGU_ENTRY_LATCHED_SS1_FULL` flags are why the logs carry "RTX3090"/"hardware untested" banners — see [evidence/README.md](evidence/README.md).

**5. USB:** FAT32, `\EFI\BOOT\BOOTX64.EFI` + the 5 firmware files in `\RTX3090-UNLOCK\ASSETS\`. Keep `\RTX3090-UNLOCK\` writable (the app logs `RUNxx\REPORT.TXT`).

**6. Run:** Secure Boot off → boot the USB → press **U** → Windows boots.

**7. Hold it on Windows:** auto-start `scripts/gpu_keepalive_light.py` at logon (put `scripts/gpu-unlock-keepalive.bat` in the Startup folder). It touches the dGPU every 100 ms so RTD3 never power-cycles it (which would reset the unlock). It must grab the card **before** the first idle — an at-logon autostart does; a manual run after login is too late.

**8. Verify:** `nvidia-smi -lgc 1500,1500`, then `py -3 tensor_bench.py` or `torch_gemm.py`; `nvidia-smi -rgc` after. At the pinned 1500 MHz, unlocked FP16 ≈ 57 TFLOPS.

## Caveats

- **Volatile:** a full power-off loses the unlock; re-run the USB each boot.
- **Windows persistence** needs the keep-alive running (the revert is RTD3 idle power-down, not a driver re-latch).
- Affects **FP16/BF16/TF32 tensor only** — games, FP32 shading and quantized/INT inference are unchanged. Normal/gaming benchmarks show **nothing**.
- **The "3090 / 24GB" labels in the evidence log are inherited upstream strings, not the real card** — this port reuses the upstream RTX 3090 / GA102 firmware and experimental build mode (`-DGU_EXPERIMENTAL_3090`, `\RTX3090-UNLOCK\` paths). The device is proven to be the 8 GB RTX 3070 Laptop inside the same log (`config[00]=249d10de`, `memory=0x2000`). See [evidence/README.md](evidence/README.md).
- One laptop, **untested elsewhere**. No VBIOS reflash; everything resets on power-off. Experimental — **use at your own risk**.

## Credits & license

Based on GPL-2.0 work by **[Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock)** and **[impacifist/Windows-GPU-UNLOCK](https://github.com/impacifist/Windows-GPU-UNLOCK)**. This adaptation is **GPL-2.0**. NVIDIA firmware and VBIOS are the property of NVIDIA and are **not redistributed** here.
