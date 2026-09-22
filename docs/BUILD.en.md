# Building and releasing

[Русский](BUILD.md) | **English**

Requirements: Git, Go 1.25+ (the supplied engine was built with 1.25.14), and Python 3.10+. The build pins a commit and verifies the exact S4 patch diff.

Linux: `bash build/build.sh`.

Windows:

```powershell
powershell -File build/build-userspace.ps1 -Go C:\Go\bin\go.exe
```

Docker from the project root: `docker build -f build/Dockerfile -t awg3-builder .`, then `docker run --rm -v "$PWD/prebuilt/kn-1012:/out" awg3-builder`. This build path was not tested when preparing the first release.

The build updates amneziawg-go only. The awg 3.1.20260812 CLI binary was inherited. An official tools source snapshot, including its build files, is attached to the release. Bit-for-bit CLI reproducibility is not claimed. See [NOTICE](../NOTICE.en.md) and BUILD-INFO.

After rebuilding the engine, update compiler information and SHA256 in BUILD-INFO.json. The packager rejects a mismatched hash rather than publishing stale metadata.

## Checks — Linux / Git Bash

```sh
sh tests/test_split_config.sh
sh tests/test_parser_edge_cases.sh
sh tests/test_service.sh
python build/package.py
```

For Go regression tests, copy tests/go_profile_smoke_test.go into device in the pinned source as router_smoke_test.go and run `go test ./device ./conn ./replay ./tai64n` for the host architecture. To repeat: `go test ./device -run 'TestRouter|TestAWGDevicePing' -count=10`. Before building a release engine, remove only the added test file: the build script requires the exact single-patch diff.

CI runs shell tests and packaging on Ubuntu; it does not emulate NDMS.

## Package

`python build/package.py` creates outputs/awg3-netcraze-arm64-userspace.tar.gz, an external .sha256, and internal SHA256SUMS. Only allowlisted files are included, without keys, personal profiles, logs, or .ko files.

The first release was published from a clean snapshot without the original workspace history. Review staged changes and the archive before every release. A hash from the same release checks integrity but is not an independent digital signature.
