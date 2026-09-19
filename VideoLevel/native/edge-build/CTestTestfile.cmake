# CMake generated Testfile for 
# Source directory: D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/native
# Build directory: D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/native/edge-build
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
if(CTEST_CONFIGURATION_TYPE MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
  add_test("zkstego_live_tests" "D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/native/edge-build/Debug/zkstego_live_tests.exe")
  set_tests_properties("zkstego_live_tests" PROPERTIES  _BACKTRACE_TRIPLES "D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/native/CMakeLists.txt;20;add_test;D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/native/CMakeLists.txt;0;")
elseif(CTEST_CONFIGURATION_TYPE MATCHES "^([Rr][Ee][Ll][Ee][Aa][Ss][Ee])$")
  add_test("zkstego_live_tests" "D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/native/edge-build/Release/zkstego_live_tests.exe")
  set_tests_properties("zkstego_live_tests" PROPERTIES  _BACKTRACE_TRIPLES "D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/native/CMakeLists.txt;20;add_test;D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/native/CMakeLists.txt;0;")
elseif(CTEST_CONFIGURATION_TYPE MATCHES "^([Mm][Ii][Nn][Ss][Ii][Zz][Ee][Rr][Ee][Ll])$")
  add_test("zkstego_live_tests" "D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/native/edge-build/MinSizeRel/zkstego_live_tests.exe")
  set_tests_properties("zkstego_live_tests" PROPERTIES  _BACKTRACE_TRIPLES "D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/native/CMakeLists.txt;20;add_test;D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/native/CMakeLists.txt;0;")
elseif(CTEST_CONFIGURATION_TYPE MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
  add_test("zkstego_live_tests" "D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/native/edge-build/RelWithDebInfo/zkstego_live_tests.exe")
  set_tests_properties("zkstego_live_tests" PROPERTIES  _BACKTRACE_TRIPLES "D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/native/CMakeLists.txt;20;add_test;D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/native/CMakeLists.txt;0;")
else()
  add_test("zkstego_live_tests" NOT_AVAILABLE)
endif()
