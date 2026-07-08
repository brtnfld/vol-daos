#------------------------------------------------------------------------------
# Re-find HDF5 in this directory's own scope
#
# src/CMakeLists.txt already calls find_package(HDF5 ...), but the IMPORTED
# targets a Config-mode find_package() creates (including h5_api_test etc.)
# are only visible in the directory scope where find_package() was called
# plus its descendants, unless the package marks them GLOBAL (HDF5's
# generated hdf5-targets.cmake does not). test/ is add_subdirectory()'d as a
# sibling of src/ from the top-level CMakeLists.txt, not a descendant of it,
# so without this, h5_api_test is invisible here even though HDF5_FOUND and
# hdf5-shared (used only inside src/) both resolve fine.
#
# No version constraint is requested here (src/CMakeLists.txt's own
# find_package(HDF5 1.14.0 ...) is untouched): HDF5's generated
# hdf5-config-version.cmake uses SameMinorVersion compatibility, which
# rejects HDF5 develop (versioned 2.x) outright against a "1.14.0" minimum,
# forcing a MODULE-mode fallback that provides no CMake targets at all. This
# call only needs to locate the package, not enforce a version guarantee --
# if h5_api_test isn't found below, that's handled explicitly.
#------------------------------------------------------------------------------
find_package(HDF5 NO_MODULE NAMES hdf5 COMPONENTS C shared)
find_package(Python3 COMPONENTS Interpreter REQUIRED)

#------------------------------------------------------------------------------
# Options
#------------------------------------------------------------------------------
option(HDF5_VOL_DAOS_TESTING_USE_SYSTEM_SERVER "Use system running server for testing." OFF)
mark_as_advanced(HDF5_VOL_DAOS_TESTING_USE_SYSTEM_SERVER)

#------------------------------------------------------------------------------
# DAOS server config
#------------------------------------------------------------------------------
# Exec
find_program(DAOS_SERVER_EXECUTABLE
  NAMES daos_server
  PATH_SUFFIXES bin sbin
  HINTS ${DAOS_HINT_DIRS}
  DOC "DAOS server executable."
)
mark_as_advanced(DAOS_SERVER_EXECUTABLE)

# Default paths
set(DAOS_LOG_DIR ${CMAKE_CURRENT_BINARY_DIR})
set(DAOS_SERVER_SOCKET_DIR ${CMAKE_CURRENT_BINARY_DIR})

# Preflags
set(DAOS_SERVER_PREFLAGS
  "-genv DAOS_DISABLE_REQ_FWD 1"
)

set(DAOS_SERVER_CONFIG_FILEPATH
  ${CMAKE_CURRENT_BINARY_DIR}/scripts/daos_server.yml
)

# Postflags
# Storage is formatted explicitly via "dmg storage format" (see daos_pool.sh.in).
set(DAOS_SERVER_POSTFLAGS
  "start -o ${DAOS_SERVER_CONFIG_FILEPATH}"
)

# Transport
set(DAOS_SERVER_TRANSPORT "ofi+tcp" CACHE STRING
  "Transport used by DAOS server for testing (sm, ofi+tcp)."
)
mark_as_advanced(DAOS_SERVER_TRANSPORT)

# Interface
set(DAOS_SERVER_IFACE "lo" CACHE STRING
  "Interface used by DAOS server for testing."
)
mark_as_advanced(DAOS_SERVER_IFACE)

# SCM size
set(DAOS_SERVER_SCM_SIZE "8" CACHE STRING
  "Size of RAM available for storage in GB."
)
mark_as_advanced(DAOS_SERVER_SCM_SIZE)

# Engine targets
set(DAOS_SERVER_TARGETS "4" CACHE STRING
  "Number of storage targets for the DAOS server engine to use. Must not exceed the number of cores available on the host."
)
mark_as_advanced(DAOS_SERVER_TARGETS)

# SCM mnt
set(DAOS_SERVER_SCM_MNT "/mnt/daos" CACHE STRING
  "Path to SCM mount point."
)
mark_as_advanced(DAOS_SERVER_SCM_MNT)

# Init config
configure_file(
   ${CMAKE_CURRENT_SOURCE_DIR}/scripts/daos_server.yml.in
   ${CMAKE_CURRENT_BINARY_DIR}/scripts/daos_server.yml
)

#------------------------------------------------------------------------------
# DAOS agent config
#------------------------------------------------------------------------------
# Exec
find_program(DAOS_AGENT_EXECUTABLE
  NAMES daos_agent
  PATH_SUFFIXES bin sbin
  HINTS ${DAOS_HINT_DIRS}
  DOC "DAOS agent executable."
)
mark_as_advanced(DAOS_AGENT_EXECUTABLE)

# Default paths
set(DAOS_AGENT_DIR ${CMAKE_CURRENT_BINARY_DIR})
set(DAOS_AGENT_SOCKET_DIR ${CMAKE_CURRENT_BINARY_DIR})

# Agent config
configure_file(
  ${CMAKE_CURRENT_SOURCE_DIR}/scripts/daos_agent.yml.in
  ${CMAKE_CURRENT_BINARY_DIR}/scripts/daos_agent.yml
)
configure_file(
  ${CMAKE_CURRENT_SOURCE_DIR}/scripts/daos_agent.sh.in
  ${CMAKE_CURRENT_BINARY_DIR}/scripts/daos_agent.sh
)
execute_process(COMMAND chmod u+x ${CMAKE_CURRENT_BINARY_DIR}/scripts/daos_agent.sh)

#------------------------------------------------------------------------------
# DAOS dmg config
#------------------------------------------------------------------------------
# Exec
find_program(DAOS_DMG_EXECUTABLE
  NAMES dmg
  PATH_SUFFIXES bin sbin
  HINTS ${DAOS_HINT_DIRS}
  DOC "DAOS dmg executable."
)
mark_as_advanced(DAOS_DMG_EXECUTABLE)

# SCM size
set(DAOS_POOL_SIZE "4" CACHE STRING
  "Size of pool created for testing in GB."
)
mark_as_advanced(DAOS_POOL_SIZE)

# Dmg config
configure_file(
  ${CMAKE_CURRENT_SOURCE_DIR}/scripts/daos_pool.sh.in
  ${CMAKE_CURRENT_BINARY_DIR}/scripts/daos_pool.sh
)
execute_process(COMMAND chmod u+x ${CMAKE_CURRENT_BINARY_DIR}/scripts/daos_pool.sh)

#------------------------------------------------------------------------------
# DAOS client config
#------------------------------------------------------------------------------

set(HDF5_VOL_TEST_PLUGIN_PATH ${CMAKE_RUNTIME_OUTPUT_DIRECTORY})
set(HDF5_VOL_TEST_PLUGIN_NAME "daos")

set(DAOS_CLIENT_ENV_VARS
  "D_LOG_FILE=${CMAKE_CURRENT_BINARY_DIR}/daos_client.log"
  "D_LOG_MASK=ERR"
  "CRT_PHY_ADDR_STR=${DAOS_SERVER_TRANSPORT}"
  "OFI_INTERFACE=${DAOS_SERVER_IFACE}"
  "DAOS_AGENT_DRPC_DIR=${DAOS_AGENT_DIR}"
  "HDF5_PLUGIN_PATH=${HDF5_VOL_TEST_PLUGIN_PATH}"
  "HDF5_VOL_CONNECTOR=${HDF5_VOL_TEST_PLUGIN_NAME}"
  # Disable automatic chunk sizing for the API tests
  "HDF5_DAOS_CHUNK_TARGET_SIZE=1073741824"
)

#------------------------------------------------------------------------------
# Test driver config
#------------------------------------------------------------------------------

set(DAOS_TEST_SERVER "")
if(NOT HDF5_VOL_DAOS_TESTING_USE_SYSTEM_SERVER)
  set(DAOS_TEST_SERVER ${DAOS_SERVER_EXECUTABLE})
  set(DAOS_INIT_COMMAND "rm -rf ${DAOS_SERVER_SCM_MNT}/* ${CMAKE_RUNTIME_OUTPUT_DIRECTORY}/*.h5")
  set(DAOS_SERVER_EXIT_COMMAND "killall -9 daos_server")
  set(DAOS_SERVER_START_MSG "DAOS I/O Engine")
  set(DAOS_CLIENT_HELPER ${CMAKE_CURRENT_BINARY_DIR}/scripts/daos_agent.sh)
  set(DAOS_CLIENT_HELPER_START_MSG "listening on")
  set(DAOS_CLIENT_HELPER_EXIT_COMMAND "killall daos_agent")
  set(DAOS_CLIENT_INIT ${CMAKE_CURRENT_BINARY_DIR}/scripts/daos_pool.sh)
  set(DAOS_CLIENT_INIT_TOKEN_REGEX "([a-f0-9]+-[a-f0-9]+-[a-f0-9]+-[a-f0-9]+-[a-f0-9]+)")
  set(DAOS_CLIENT_INIT_TOKEN_VAR "DAOS_POOL")
endif()

#------------------------------------------------------------------------------
# DAOS VOL specific tests
#------------------------------------------------------------------------------
add_subdirectory(daos_vol)

#------------------------------------------------------------------------------
# HDF5 API tests
#
# Consumes the h5_api_test / h5_api_test_parallel (+ extra native test)
# binaries and CMake targets installed by an HDF5 build configured with
# -DHDF5_TEST_API_INSTALL=ON. See docs/api-tests-migration.md for the design.
#
# Tests run through test/driver/h5vl_test_driver.py, a small Python script
# (no build step, no dependencies beyond the standard library) that starts
# the DAOS server/agent/pool around each client invocation, extracts the
# pool UUID, and injects the connector's environment variables. Runs
# unmodified when HDF5_VOL_DAOS_TESTING_USE_SYSTEM_SERVER=ON too
# (DAOS_TEST_SERVER empty): the script just skips server management and
# runs the client directly, still handling env injection and error-string
# scanning.
#------------------------------------------------------------------------------

set(HDF5_VOL_TEST_ENABLE_PARALLEL "ON" CACHE BOOL "Enable testing in parallel (requires MPI).")

option(HDF5_VOL_DAOS_TEST_API_ENABLE_ASYNC
  "Enable HDF5 API async interface tests (requires HDF5 built with -DHDF5_TEST_API_ENABLE_ASYNC=ON)."
  OFF)
mark_as_advanced(HDF5_VOL_DAOS_TEST_API_ENABLE_ASYNC)

set(H5VL_TEST_DRIVER ${CMAKE_CURRENT_SOURCE_DIR}/driver/h5vl_test_driver.py)

# Interface list must match HDF5_API_TESTS in the HDF5 install's
# test/API/CMakeLists.txt.
set(HDF5_API_TESTS
  attribute
  dataset
  datatype
  file
  group
  link
  misc
  object
)
if(HDF5_VOL_DAOS_TEST_API_ENABLE_ASYNC)
  list(APPEND HDF5_API_TESTS async)
endif()

# Extra native HDF5 tests exercised through the same connector/driver setup.
# Names must match HDF5_API_TESTS_EXTRA / HDF5_API_PAR_TESTS_EXTRA in the
# HDF5 install's test/API and testpar/API CMakeLists.txt.
set(HDF5_API_TESTS_EXTRA testhdf5)
set(HDF5_API_PAR_TESTS_EXTRA t_bigio t_pshutdown t_shapesame testphdf5)

# Per-interface subtest exclusions for gaps that have no H5VL capability flag
# to gate on (see docs/api-tests-migration.md, section 3, layer 3). Only
# supported against HDF5 develop, where h5_api_test accepts "-x <subtest>";
# 1.14.6's API tests only support whole-interface selection. Populate these
# from an actual DAOS test run -- do not guess subtest names.
foreach(_h5_api_iface ${HDF5_API_TESTS})
  set(HDF5_API_TEST_${_h5_api_iface}_EXCLUDES "" CACHE STRING
    "Subtests to exclude (via -x) from the '${_h5_api_iface}' HDF5 API test interface.")
  mark_as_advanced(HDF5_API_TEST_${_h5_api_iface}_EXCLUDES)
endforeach()

# Same -x mechanism for the extra native HDF5 test binaries, which use
# HDF5's standard AddTest/-x test framework. testphdf5's h5oflusherror
# subtest specifically tests a native-VOL parallel metadata-cache
# limitation that does not apply to this (or any non-native) connector -
# DAOS VOL correctly succeeds where that subtest expects H5Oflush to fail.
set(HDF5_API_TEST_EXTRA_testphdf5_EXCLUDES "h5oflusherror" CACHE STRING
  "Subtests to exclude (via -x) from the 'testphdf5' native HDF5 test binary.")
foreach(_h5_api_extra ${HDF5_API_TESTS_EXTRA} ${HDF5_API_PAR_TESTS_EXTRA})
  set(HDF5_API_TEST_EXTRA_${_h5_api_extra}_EXCLUDES "" CACHE STRING
    "Subtests to exclude (via -x) from the '${_h5_api_extra}' native HDF5 test binary.")
  mark_as_advanced(HDF5_API_TEST_EXTRA_${_h5_api_extra}_EXCLUDES)
endforeach()

if(NOT TARGET h5_api_test)
  message(WARNING
    "h5_api_test target not found -- HDF5 was not built with "
    "-DHDF5_TEST_API_INSTALL=ON, so no HDF5 API tests were registered. "
    "See docs/api-tests-migration.md.")
else()
  # Flags shared by every h5vl_test_driver.py invocation.
  set(H5VL_TEST_DRIVER_COMMON_ARGS
    --server-start-msg "${DAOS_SERVER_START_MSG}"
    --server-exit-command "${DAOS_SERVER_EXIT_COMMAND}"
    --client-helper-start-msg "${DAOS_CLIENT_HELPER_START_MSG}"
    --client-helper-exit-command "${DAOS_CLIENT_HELPER_EXIT_COMMAND}"
    --client-init-token-regex "${DAOS_CLIENT_INIT_TOKEN_REGEX}"
    --client-init-token-var "${DAOS_CLIENT_INIT_TOKEN_VAR}"
    --init-command "${DAOS_INIT_COMMAND}"
    --mpiexec "${MPIEXEC_EXECUTABLE}"
    --mpiexec-numproc-flag "${MPIEXEC_NUMPROC_FLAG}"
    --mpiexec-max-numprocs "${MPIEXEC_MAX_NUMPROCS}"
    --mpiexec-preflags "${MPIEXEC_PREFLAGS}"
    --mpiexec-postflags "${MPIEXEC_POSTFLAGS}"
    --mpiexec-server-max-numprocs "1"
    --mpiexec-server-preflags "${DAOS_SERVER_PREFLAGS}"
    --mpiexec-server-postflags "${DAOS_SERVER_POSTFLAGS}"
    --allow-server-errors
  )
  foreach(_var ${DAOS_CLIENT_ENV_VARS})
    list(APPEND H5VL_TEST_DRIVER_COMMON_ARGS --client-env ${_var})
  endforeach()
  if(DAOS_TEST_SERVER)
    list(APPEND H5VL_TEST_DRIVER_COMMON_ARGS
      --server ${DAOS_TEST_SERVER}
      --client-helper ${DAOS_CLIENT_HELPER}
      --client-init ${DAOS_CLIENT_INIT}
    )
  endif()

  # Serial API tests, one ctest entry per interface, run sequentially since
  # they share one DAOS server/pool instance.
  set(_h5_api_last_test "")
  foreach(api_test ${HDF5_API_TESTS})
    set(_h5_api_exclude_args "")
    foreach(_excl ${HDF5_API_TEST_${api_test}_EXCLUDES})
      list(APPEND _h5_api_exclude_args -x ${_excl})
    endforeach()

    add_test(NAME "h5_api_test_${api_test}"
      COMMAND ${Python3_EXECUTABLE} ${H5VL_TEST_DRIVER}
      ${H5VL_TEST_DRIVER_COMMON_ARGS}
      --serial
      --client $<TARGET_FILE:h5_api_test> ${api_test} ${_h5_api_exclude_args}
    )
    set_tests_properties("h5_api_test_${api_test}" PROPERTIES DEPENDS "${_h5_api_last_test}")
    set(_h5_api_last_test "h5_api_test_${api_test}")
  endforeach()

  foreach(hdf5_test ${HDF5_API_TESTS_EXTRA})
    if(TARGET ${hdf5_test})
      set(_h5_api_extra_exclude_args "")
      foreach(_excl ${HDF5_API_TEST_EXTRA_${hdf5_test}_EXCLUDES})
        list(APPEND _h5_api_extra_exclude_args -x ${_excl})
      endforeach()

      add_test(NAME "h5_api_ext_test_${hdf5_test}"
        COMMAND ${Python3_EXECUTABLE} ${H5VL_TEST_DRIVER}
        ${H5VL_TEST_DRIVER_COMMON_ARGS}
        --serial
        --client $<TARGET_FILE:${hdf5_test}> ${_h5_api_extra_exclude_args}
      )
    endif()
  endforeach()

  if(HDF5_VOL_TEST_ENABLE_PARALLEL AND TARGET h5_api_test_parallel)
    set(_h5_api_last_test "")
    foreach(api_test ${HDF5_API_TESTS})
      add_test(NAME "h5_api_test_parallel_${api_test}"
        COMMAND ${Python3_EXECUTABLE} ${H5VL_TEST_DRIVER}
        ${H5VL_TEST_DRIVER_COMMON_ARGS}
        --client $<TARGET_FILE:h5_api_test_parallel> ${api_test}
      )
      set_tests_properties("h5_api_test_parallel_${api_test}" PROPERTIES DEPENDS "${_h5_api_last_test}")
      set(_h5_api_last_test "h5_api_test_parallel_${api_test}")
    endforeach()

    foreach(hdf5_test ${HDF5_API_PAR_TESTS_EXTRA})
      if(TARGET ${hdf5_test})
        set(_h5_api_extra_exclude_args "")
        foreach(_excl ${HDF5_API_TEST_EXTRA_${hdf5_test}_EXCLUDES})
          list(APPEND _h5_api_extra_exclude_args -x ${_excl})
        endforeach()

        add_test(NAME "h5_api_test_parallel_${hdf5_test}"
          COMMAND ${Python3_EXECUTABLE} ${H5VL_TEST_DRIVER}
          ${H5VL_TEST_DRIVER_COMMON_ARGS}
          --client $<TARGET_FILE:${hdf5_test}> ${_h5_api_extra_exclude_args}
        )
      endif()
    endforeach()
  endif()
endif()
