cmake_minimum_required(VERSION 3.20)
project(zkstego_cavlc_native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(ZKSTEGO_WARNINGS "Enable compiler warnings (-Wall -Wextra / /W4; never -Werror)" ON)
option(ZKSTEGO_SANITIZE "Build with AddressSanitizer + UndefinedBehaviorSanitizer (GCC/Clang)" OFF)

if(MSVC)
  # Sources and test literals are UTF-8 (the repository path itself is not ASCII).
  add_compile_options(/utf-8)
endif()
if(ZKSTEGO_WARNINGS)
  if(MSVC)
    add_compile_options(/W4)
  else()
    add_compile_options(-Wall -Wextra)
  endif()
endif()
if(ZKSTEGO_SANITIZE)
  if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
    add_link_options(-fsanitize=address,undefined)
  else()
    message(WARNING "ZKSTEGO_SANITIZE is only supported with GCC/Clang; ignoring")
  endif()
endif()

add_library(zkstego_cavlc_stream STATIC src/cavlc_stream.cpp)
target_include_directories(zkstego_cavlc_stream PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
if(WIN32)
  target_link_libraries(zkstego_cavlc_stream PRIVATE bcrypt)
else()
  find_package(OpenSSL REQUIRED COMPONENTS Crypto)
  target_link_libraries(zkstego_cavlc_stream PRIVATE OpenSSL::Crypto)
endif()

add_executable(zkstego_cavlc_stream_tests tests/cavlc_stream_tests.cpp)
target_link_libraries(zkstego_cavlc_stream_tests PRIVATE zkstego_cavlc_stream)
target_compile_definitions(zkstego_cavlc_stream_tests PRIVATE
  ZKSTEGO_PROJECT_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}/..")

# Channel CLI: the authenticated CAVLC segment protocol (file and live modes).
add_executable(zkstego_blind_bits tools/blind_bits.cpp)
target_link_libraries(zkstego_blind_bits PRIVATE zkstego_cavlc_stream)

# Read-only inspection: JSON trace, macroblock detail, text summary, segment schedule.
add_executable(zkstego_inspect tools/inspect.cpp)
target_link_libraries(zkstego_inspect PRIVATE zkstego_cavlc_stream)

# Both tools enter through wmain on Windows (Unicode paths).
if(MINGW)
  target_link_options(zkstego_blind_bits PRIVATE -municode)
  target_link_options(zkstego_inspect PRIVATE -municode)
endif()

include(CTest)
if(BUILD_TESTING)
  add_test(NAME zkstego_cavlc_stream_tests COMMAND zkstego_cavlc_stream_tests)
endif()
