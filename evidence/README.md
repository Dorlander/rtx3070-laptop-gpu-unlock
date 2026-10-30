# Evidence — read this first

This folder holds `unlock-REPORT.TXT`, the verbatim log the UEFI unlock app wrote to the USB stick during the transaction on the actual laptop. It is **unedited on purpose** — it is the machine's own record, not a writeup.

## Two things in the raw log look wrong at a glance — they are inherited upstream labels, not the real device

**1. "RTX3090" and "24GB".** Line 1 reads `RTX3090 AMD EXPERIMENTAL MANUAL UNLOCK` and line 87 reads `... exact RTX3090 24GB ...`. The real card is an **RTX 3070 Laptop, GA104, 8 GB**.

These strings are emitted by the upstream experimental build mode this port reuses. The unlock is compiled with `-DGU_EXPERIMENTAL_3090 -DGU_ENTRY_LATCHED_SS1_FULL`; in upstream `internal-boot/unlock/build.ps1` the `-ExperimentalUnlock` path hard-codes the output name `RTX3090-EXPERIMENTAL-…` and the `\RTX3090-UNLOCK\` USB paths. The adaptation reuses the upstream RTX 3090 / GA102 **firmware assets** (`booter_load_ga102`, `v67-ga102-610.43.03`, `gsp_ga10x`, `gsp_boot_ga102`, `gsp_boot_desc_ga102`) on a GA104 card, which is where the "3090" lineage comes from.

The **same log proves the real device**:

| In the log | Value | Means |
|---|---|---|
| `config[00]=249d10de` | PCI `10de:249d` | GeForce **RTX 3070 Laptop** (the 3090 is `10de:2204`) |
| `memory=0x2000` / `fb_mb=0x2000` | 8192 MiB | **8 GB** (a 3090 would be 24 GB / `0x6000`) |
| `chip=0xb74000a1` | GA104 | not GA102 (`0xb720…`) |

**2. "Hardware success unverified" / "hardware untested".** These are the build mode's pre-arming diagnostic banners, printed *before* the write. The realized outcome is the final transaction result at the end of the file: `result=0 … clean=1` — the PCIe FLR completed and the post-FLR selectors held (`SS0=88888888 SS1=00000008`).

## What this log does and does not prove

It proves the **UEFI unlock transaction ran and completed cleanly** on this card. It does **not** contain throughput numbers — a pre-boot UEFI app cannot run a tensor benchmark. The FP16/BF16/TF32 speedup is a separate measurement made in Windows with `scripts/tensor_bench.py` and `scripts/torch_gemm.py`; see the **Result** section of the top-level `README.md` and `COMPATIBILITY-REPORT.md`.
