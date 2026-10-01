cmake_minimum_required(VERSION 3.11)
project(zkstego_isw21_opening_smoke LANGUAGES C CXX)

if(NOT DEFINED ISW21_SOURCE_DIR)
    message(FATAL_ERROR "Set ISW21_SOURCE_DIR to the pinned lattice-zksnark checkout")
endif()

add_subdirectory("${ISW21_SOURCE_DIR}" "${CMAKE_BINARY_DIR}/isw21")

add_executable(isw21_r1cs_opening_smoke opening_smoke.cpp)
target_include_directories(isw21_r1cs_opening_smoke PRIVATE "${ISW21_SOURCE_DIR}")
target_link_libraries(isw21_r1cs_opening_smoke PRIVATE lwe_interface)
target_compile_features(isw21_r1cs_opening_smoke PRIVATE cxx_std_17)

find_program(BASH_EXECUTABLE bash)
if(BASH_EXECUTABLE)
    enable_testing()
    add_test(
        NAME isw21_split_process_verifier
        COMMAND "${BASH_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/test_split_process.sh"
                "$<TARGET_FILE:isw21_r1cs_opening_smoke>")
endif()

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(isw21_r1cs_opening_smoke PRIVATE
        -Wall -Wextra -Wpedantic -maes -msse2 -msse3 -mpopcnt)
endif()
