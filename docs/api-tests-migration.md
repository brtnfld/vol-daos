# HDF5 API test suite migration

`test/` no longer depends on the `HDFGroup/vol-tests` submodule. CI instead
builds HDF5 from source as the top-level project and pulls this connector
in as an `HDF5_VOL_ALLOW_EXTERNAL` subproject, the same mechanism HDF5's own
CI uses to test other external VOL connectors (see `vol_async.yml`,
`vol_cache.yml`, and `vol_rest.yml` in `HDFGroup/hdf5`'s
`.github/workflows/`). HDF5's own `test/API`/`testpar/API` suite then
registers this connector's ctest entries automatically.

## How it's wired

CI configures HDF5 with:

```
-DHDF5_VOL_ALLOW_EXTERNAL=LOCAL_DIR
-DHDF5_VOL_PATH01=<path to this checkout>
-DHDF5_VOL_VOL-DAOS_NAME=daos
-DHDF5_VOL_VOL-DAOS_TEST_PARALLEL=ON
```

HDF5's `CMakeVOL.cmake` `add_subdirectory()`s this repo directly into its
own build, auto-stripping this project's `find_package(HDF5 ...)` calls
(they'd conflict with targets HDF5's own in-progress build is generating)
and pre-setting `HDF5_FOUND`/`HDF5_LIBRARIES`/etc. for this project to
consume instead. `test/API/CMakeLists.txt` then registers one
`HDF5_VOL_vol-daos-h5_api_test_<iface>` ctest entry per API test interface,
plus `HDF5_VOL_vol-daos-h5_api_ext_test_<name>` entries for this
connector's own native tests (`test/daos_vol`'s `h5daos_test_*` binaries,
exposed via the `HDF5_API_EXT_SERIAL_TESTS`/`HDF5_API_EXT_PARALLEL_TESTS`
variables `test/daos_vol/CMakeLists.txt` sets).

This project does not run its own test-orchestration driver. The DAOS
server, agent, and pool are started once per CI job via plain shell steps
(`ci.yml`), not per test -- the same pattern HDF5's own CI uses to start
HSDS once for `vol-rest`. `test/CMakeLists.txt` still renders
`daos_server.yml`/`daos_agent.sh`/`daos_pool.sh` from their `.in` templates
via `configure_file()`; CI locates and runs them directly.

## Handling unsupported features

Where the test suite checks `H5VL_CAP_FLAG_*` before exercising a feature,
no exclusion is needed -- the connector's capability query already tells
the test to skip it. Gaps with no capability flag to gate on are excluded
at the ctest level in `ci.yml` (see "Known gaps" below); HDF5's own driver
mechanism for finer-grained per-subtest exclusion (`-x <subtest>`) is not
used here since this project doesn't run through it.

## Known gaps

`ci.yml`'s `ctest` invocation excludes the following as known, tracked
connector gaps rather than regressions:

- `HDF5_VOL_vol-daos-h5_api_test_attribute` -- decreasing-order
  (`H5_ITER_DEC`) attribute iteration is unsupported (`src/daos_vol_attr.c`).
- `HDF5_VOL_vol-daos-h5_api_ext_test_testhdf5` -- paginated attribute
  name/index resolution bug, only triggered once a group holds hundreds of
  attributes.
