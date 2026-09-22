cmake_minimum_required(VERSION 3.20)
project(zkstego_cavlc_native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(zkstego_cavlc_stream STATIC src/cavlc_stream.cpp)
target_include_directories(zkstego_cavlc_stream PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

add_executable(zkstego_cavlc_stream_tests tests/cavlc_stream_tests.cpp)
target_link_libraries(zkstego_cavlc_stream_tests PRIVATE zkstego_cavlc_stream)

add_executable(zkstego_idr_inspect tools/idr_inspect.cpp)
target_link_libraries(zkstego_idr_inspect PRIVATE zkstego_cavlc_stream)

include(CTest)
if(BUILD_TESTING)
  add_test(NAME zkstego_cavlc_stream_tests COMMAND zkstego_cavlc_stream_tests)
endif()
