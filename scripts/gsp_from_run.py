#!/usr/bin/env python3
# Extract GSP firmware (gsp_ga10x.bin) + NVIDIA LICENSE from the 610.43.03
# .run installer on Windows, using the Python `zstandard` module instead of a
# zstd binary. Run with: py -3 -P gsp_from_run.py <run> <outdir>
import sys, re, tarfile
from pathlib import Path
import zstandard

VERSION = "610.43.03"
HEADER_BYTES = 1 << 20
FIRMWARE = ("firmware/gsp_ga10x.bin",)
NOTICE = "LICENSE"


def payload_offset(installer: Path) -> int:
    with installer.open("rb") as f:
        header = f.read(HEADER_BYTES)
    ver = re.search(rb"^version_string=([0-9.]+)$", header, re.M)
    skip = re.search(rb"^skip=(\d+)$", header, re.M)
    if not ver or not skip:
        raise ValueError("not an NVIDIA makeself installer")
    if ver[1].decode() != VERSION:
        raise ValueError(f"installer version {ver[1].decode()}, expected {VERSION}")
    off = 0
    for _ in range(int(skip[1]) - 1):
        nl = header.find(b"\n", off)
        if nl < 0:
            raise ValueError("header shorter than skip count")
        off = nl + 1
    return off


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} <NVIDIA-Linux-x86_64-{VERSION}.run> <outdir>")
    run = Path(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    want = set(FIRMWARE) | {NOTICE}
    got = {}
    off = payload_offset(run)
    with run.open("rb") as f:
        f.seek(off)
        with zstandard.ZstdDecompressor().stream_reader(f) as reader:
            with tarfile.open(fileobj=reader, mode="r|") as tar:
                for m in tar:
                    if m.name in want and m.isfile():
                        got[m.name] = tar.extractfile(m).read()
    missing = sorted(want - got.keys())
    if missing:
        raise ValueError("missing members: " + ", ".join(missing))
    for n in FIRMWARE:
        (out / Path(n).name).write_bytes(got[n])
        print(f"{Path(n).name}: {len(got[n])} bytes")
    (out / "NVIDIA-LICENSE").write_bytes(got[NOTICE])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, tarfile.TarError, zstandard.ZstdError) as e:
        raise SystemExit(f"gsp extract failed: {e}")
