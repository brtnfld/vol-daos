# HDF5 API test suite migration

`test/` no longer depends on the `HDFGroup/vol-tests` submodule. Instead it
runs HDF5's own in-tree API test suite (`test/API` and `testpar/API`),
built as part of an HDF5 installation configured with
`-DHDF5_TEST_API_INSTALL=ON`.

## How it's wired

`test/CMakeLists.txt` looks for the `h5_api_test` CMake target that HDF5's
install exports. If it isn't found (HDF5 wasn't built with API tests), the
"HDF5 API tests" section is skipped with a warning and the rest of the
connector's test suite (`test/daos_vol`) is unaffected.

When found, one ctest entry is registered per API test interface
(`h5_api_test_attribute`, `h5_api_test_dataset`, ...) plus one per extra
native HDF5 test binary (`h5_api_ext_test_testhdf5`,
`h5_api_test_parallel_t_bigio`, etc.), each invoking
`test/driver/h5vl_test_driver.py`.

`h5vl_test_driver.py` is a small, dependency-free Python 3 script. For each
test it starts the DAOS server and agent, runs `daos_pool.sh` to create a
pool and capture its UUID, injects that UUID and the connector's
environment variables (`HDF5_VOL_CONNECTOR`, `HDF5_PLUGIN_PATH`, etc.) into
the test binary's environment, then runs the test and reports its exit
code. It also scans all process output for known error substrings, since a
hung or crashed DAOS server does not always propagate as a nonzero exit
code from the test binary itself. Setting
`HDF5_VOL_DAOS_TESTING_USE_SYSTEM_SERVER=ON` skips server/agent management
and runs tests against an already-running DAOS instance instead.

## Handling unsupported features

Some HDF5 API test coverage exercises functionality this connector
intentionally does not implement. These are excluded in two ways:

- **Capability flags**: where the test suite checks
  `H5VL_CAP_FLAG_*` before exercising a feature, no exclusion is needed --
  the connector's capability query already tells the test to skip it.
- **Subtest exclusion**: for gaps the test suite doesn't gate behind a
  capability flag, `test/CMakeLists.txt` exposes
  `HDF5_API_TEST_<iface>_EXCLUDES` and
  `HDF5_API_TEST_EXTRA_<name>_EXCLUDES` cache variables, passed to the
  driver as `-x <subtest>`. This only works against HDF5 develop's
  AddTest-based test framework; HDF5 1.14.6's API tests only support
  whole-interface selection.

`HDF5_API_TEST_EXTRA_testphdf5_EXCLUDES` defaults to `h5oflusherror`: that
subtest asserts that `H5Oflush` *fails*, documenting a native-VOL-only
parallel metadata-cache limitation that does not apply to this connector.

## Known gaps

The CI workflow (`.github/workflows/ci.yml`) excludes the following ctest
entries as known, tracked connector gaps rather than regressions:

- `h5_api_test_attribute` -- decreasing-order (`H5_ITER_DEC`) attribute
  iteration is unsupported (`src/daos_vol_attr.c`).
- `h5_api_ext_test_testhdf5` -- paginated attribute name/index resolution
  bug, triggered once a group holds hundreds of attributes.
- `h5_api_test_parallel_t_bigio` -- times out, likely due to DAOS
  RAM-backed storage exhaustion from running many sequential DAOS
  server/pool instances in one CI container.
