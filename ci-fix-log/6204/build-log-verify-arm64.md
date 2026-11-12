bx265.a
#7 50.65 gmake[2]: Leaving directory '/x265/build-release'
#7 50.67 [ 77%] Built target x265-static
#7 50.67 /usr/bin/gmake  -f test/CMakeFiles/TestBench.dir/build.make test/CMakeFiles/TestBench.dir/depend
#7 50.67 gmake[2]: Entering directory '/x265/build-release'
#7 50.67 cd /x265/build-release && /usr/bin/cmake -E cmake_depends "Unix Makefiles" /x265/source /x265/source/test /x265/build-release /x265/build-release/test /x265/build-release/test/CMakeFiles/TestBench.dir/DependInfo.cmake "--color="
#7 50.68 gmake[2]: Leaving directory '/x265/build-release'
#7 50.68 /usr/bin/gmake  -f test/CMakeFiles/TestBench.dir/build.make test/CMakeFiles/TestBench.dir/build
#7 50.68 gmake[2]: Entering directory '/x265/build-release'
#7 50.69 [ 78%] Building CXX object test/CMakeFiles/TestBench.dir/testbench.cpp.o
#7 50.70 [ 81%] Building CXX object test/CMakeFiles/TestBench.dir/pixelharness.cpp.o
#7 50.70 [ 81%] Building CXX object test/CMakeFiles/TestBench.dir/mbdstharness.cpp.o
#7 50.70 [ 82%] Building CXX object test/CMakeFiles/TestBench.dir/intrapredharness.cpp.o
#7 50.70 cd /x265/build-release/test && /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT test/CMakeFiles/TestBench.dir/testbench.cpp.o -MF CMakeFiles/TestBench.dir/testbench.cpp.o.d -o CMakeFiles/TestBench.dir/testbench.cpp.o -c /x265/source/test/testbench.cpp
#7 50.70 [ 83%] Building CXX object test/CMakeFiles/TestBench.dir/ipfilterharness.cpp.o
#7 50.70 cd /x265/build-release/test && /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT test/CMakeFiles/TestBench.dir/pixelharness.cpp.o -MF CMakeFiles/TestBench.dir/pixelharness.cpp.o.d -o CMakeFiles/TestBench.dir/pixelharness.cpp.o -c /x265/source/test/pixelharness.cpp
#7 50.70 cd /x265/build-release/test && /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT test/CMakeFiles/TestBench.dir/mbdstharness.cpp.o -MF CMakeFiles/TestBench.dir/mbdstharness.cpp.o.d -o CMakeFiles/TestBench.dir/mbdstharness.cpp.o -c /x265/source/test/mbdstharness.cpp
#7 50.70 cd /x265/build-release/test && /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT test/CMakeFiles/TestBench.dir/intrapredharness.cpp.o -MF CMakeFiles/TestBench.dir/intrapredharness.cpp.o.d -o CMakeFiles/TestBench.dir/intrapredharness.cpp.o -c /x265/source/test/intrapredharness.cpp
#7 50.70 cd /x265/build-release/test && /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT test/CMakeFiles/TestBench.dir/ipfilterharness.cpp.o -MF CMakeFiles/TestBench.dir/ipfilterharness.cpp.o.d -o CMakeFiles/TestBench.dir/ipfilterharness.cpp.o -c /x265/source/test/ipfilterharness.cpp
#7 50.72 /usr/bin/c++ -fPIC -O3 -O3 -DNDEBUG -Wl,-Bsymbolic,-znoexecstack -Wl,--dependency-file=CMakeFiles/x265-shared.dir/link.d -shared -Wl,-soname,libx265.so.192 -o libx265.so.192 asm.S.o "mc-a.S.o" "sad-a.S.o" "pixel-util.S.o" ipfilter8.S.o encoder/CMakeFiles/encoder.dir/analysis.cpp.o encoder/CMakeFiles/encoder.dir/search.cpp.o encoder/CMakeFiles/encoder.dir/bitcost.cpp.o encoder/CMakeFiles/encoder.dir/motion.cpp.o encoder/CMakeFiles/encoder.dir/slicetype.cpp.o encoder/CMakeFiles/encoder.dir/frameencoder.cpp.o encoder/CMakeFiles/encoder.dir/framefilter.cpp.o encoder/CMakeFiles/encoder.dir/level.cpp.o encoder/CMakeFiles/encoder.dir/nal.cpp.o encoder/CMakeFiles/encoder.dir/sei.cpp.o encoder/CMakeFiles/encoder.dir/sao.cpp.o encoder/CMakeFiles/encoder.dir/entropy.cpp.o encoder/CMakeFiles/encoder.dir/dpb.cpp.o encoder/CMakeFiles/encoder.dir/ratecontrol.cpp.o encoder/CMakeFiles/encoder.dir/reference.cpp.o encoder/CMakeFiles/encoder.dir/encoder.cpp.o encoder/CMakeFiles/encoder.dir/api.cpp.o encoder/CMakeFiles/encoder.dir/weightPrediction.cpp.o "common/CMakeFiles/common.dir/aarch64/asm-primitives.cpp.o" common/CMakeFiles/common.dir/primitives.cpp.o common/CMakeFiles/common.dir/pixel.cpp.o common/CMakeFiles/common.dir/dct.cpp.o common/CMakeFiles/common.dir/lowpassdct.cpp.o common/CMakeFiles/common.dir/ipfilter.cpp.o common/CMakeFiles/common.dir/intrapred.cpp.o common/CMakeFiles/common.dir/loopfilter.cpp.o common/CMakeFiles/common.dir/constants.cpp.o common/CMakeFiles/common.dir/cpu.cpp.o common/CMakeFiles/common.dir/version.cpp.o common/CMakeFiles/common.dir/threading.cpp.o common/CMakeFiles/common.dir/threadpool.cpp.o common/CMakeFiles/common.dir/wavefront.cpp.o common/CMakeFiles/common.dir/md5.cpp.o common/CMakeFiles/common.dir/bitstream.cpp.o common/CMakeFiles/common.dir/yuv.cpp.o common/CMakeFiles/common.dir/shortyuv.cpp.o common/CMakeFiles/common.dir/picyuv.cpp.o common/CMakeFiles/common.dir/common.cpp.o common/CMakeFiles/common.dir/param.cpp.o common/CMakeFiles/common.dir/frame.cpp.o common/CMakeFiles/common.dir/framedata.cpp.o common/CMakeFiles/common.dir/cudata.cpp.o common/CMakeFiles/common.dir/slice.cpp.o common/CMakeFiles/common.dir/lowres.cpp.o common/CMakeFiles/common.dir/piclist.cpp.o common/CMakeFiles/common.dir/predict.cpp.o common/CMakeFiles/common.dir/scalinglist.cpp.o common/CMakeFiles/common.dir/quant.cpp.o common/CMakeFiles/common.dir/deblock.cpp.o common/CMakeFiles/common.dir/scaler.cpp.o  -lpthread -lrt -ldl
#7 50.72 /usr/bin/cmake -E cmake_symlink_library libx265.so.192 libx265.so.192 libx265.so
#7 50.74 gmake[2]: Leaving directory '/x265/build-release'
#7 50.75 [ 83%] Built target x265-shared
#7 50.75 /usr/bin/gmake  -f CMakeFiles/cli.dir/build.make CMakeFiles/cli.dir/depend
#7 50.76 gmake[2]: Entering directory '/x265/build-release'
#7 50.76 cd /x265/build-release && /usr/bin/cmake -E cmake_depends "Unix Makefiles" /x265/source /x265/source /x265/build-release /x265/build-release /x265/build-release/CMakeFiles/cli.dir/DependInfo.cmake "--color="
#7 50.77 gmake[2]: Leaving directory '/x265/build-release'
#7 50.77 /usr/bin/gmake  -f CMakeFiles/cli.dir/build.make CMakeFiles/cli.dir/build
#7 50.77 gmake[2]: Entering directory '/x265/build-release'
#7 50.79 [ 85%] Building CXX object CMakeFiles/cli.dir/input/input.cpp.o
#7 50.79 [ 86%] Building CXX object CMakeFiles/cli.dir/input/y4m.cpp.o
#7 50.79 /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT CMakeFiles/cli.dir/input/input.cpp.o -MF CMakeFiles/cli.dir/input/input.cpp.o.d -o CMakeFiles/cli.dir/input/input.cpp.o -c /x265/source/input/input.cpp
#7 50.79 [ 88%] Building CXX object CMakeFiles/cli.dir/output/raw.cpp.o
#7 50.79 [ 88%] Building CXX object CMakeFiles/cli.dir/output/y4m.cpp.o
#7 50.79 [ 90%] Building CXX object CMakeFiles/cli.dir/output/reconplay.cpp.o
#7 50.79 [ 91%] Building CXX object CMakeFiles/cli.dir/output/yuv.cpp.o
#7 50.79 [ 92%] Building CXX object CMakeFiles/cli.dir/output/output.cpp.o
#7 50.79 /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT CMakeFiles/cli.dir/input/y4m.cpp.o -MF CMakeFiles/cli.dir/input/y4m.cpp.o.d -o CMakeFiles/cli.dir/input/y4m.cpp.o -c /x265/source/input/y4m.cpp
#7 50.79 [ 93%] Building CXX object CMakeFiles/cli.dir/x265.cpp.o
#7 50.79 [ 95%] Building CXX object CMakeFiles/cli.dir/input/yuv.cpp.o
#7 50.79 /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT CMakeFiles/cli.dir/output/output.cpp.o -MF CMakeFiles/cli.dir/output/output.cpp.o.d -o CMakeFiles/cli.dir/output/output.cpp.o -c /x265/source/output/output.cpp
#7 50.79 /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT CMakeFiles/cli.dir/output/raw.cpp.o -MF CMakeFiles/cli.dir/output/raw.cpp.o.d -o CMakeFiles/cli.dir/output/raw.cpp.o -c /x265/source/output/raw.cpp
#7 50.79 /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT CMakeFiles/cli.dir/input/yuv.cpp.o -MF CMakeFiles/cli.dir/input/yuv.cpp.o.d -o CMakeFiles/cli.dir/input/yuv.cpp.o -c /x265/source/input/yuv.cpp
#7 50.79 /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT CMakeFiles/cli.dir/output/reconplay.cpp.o -MF CMakeFiles/cli.dir/output/reconplay.cpp.o.d -o CMakeFiles/cli.dir/output/reconplay.cpp.o -c /x265/source/output/reconplay.cpp
#7 50.79 /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT CMakeFiles/cli.dir/output/y4m.cpp.o -MF CMakeFiles/cli.dir/output/y4m.cpp.o.d -o CMakeFiles/cli.dir/output/y4m.cpp.o -c /x265/source/output/y4m.cpp
#7 50.79 [ 96%] Building CXX object CMakeFiles/cli.dir/x265cli.cpp.o
#7 50.79 /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT CMakeFiles/cli.dir/output/yuv.cpp.o -MF CMakeFiles/cli.dir/output/yuv.cpp.o.d -o CMakeFiles/cli.dir/output/yuv.cpp.o -c /x265/source/output/yuv.cpp
#7 50.80 [ 97%] Building CXX object CMakeFiles/cli.dir/abrEncApp.cpp.o
#7 50.80 /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT CMakeFiles/cli.dir/x265.cpp.o -MF CMakeFiles/cli.dir/x265.cpp.o.d -o CMakeFiles/cli.dir/x265.cpp.o -c /x265/source/x265.cpp
#7 50.80 /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT CMakeFiles/cli.dir/x265cli.cpp.o -MF CMakeFiles/cli.dir/x265cli.cpp.o.d -o CMakeFiles/cli.dir/x265cli.cpp.o -c /x265/source/x265cli.cpp
#7 50.80 /usr/bin/c++ -DEXPORT_C_API=1 -DHAVE_ARMV6=0 -DHAVE_INT_TYPES_H=1 -DHAVE_NEON -DHIGH_BIT_DEPTH=0 -DX265_ARCH_ARM64=1 -DX265_ARCH_ARM=1 -DX265_DEPTH=8 -DX265_NS=x265 -D__STDC_LIMIT_MACROS=1 -I/x265/source/. -I/x265/source/common -I/x265/source/encoder -I/x265/build-release -O3 -O3 -DNDEBUG   -Wall -Wextra -Wshadow -Wno-class-memaccess -std=gnu++98 -fPIC -fPIC -Wno-array-bounds -ffast-math -fno-exceptions -MD -MT CMakeFiles/cli.dir/abrEncApp.cpp.o -MF CMakeFiles/cli.dir/abrEncApp.cpp.o.d -o CMakeFiles/cli.dir/abrEncApp.cpp.o -c /x265/source/abrEncApp.cpp
#7 52.26 [ 98%] Linking CXX executable x265
#7 52.26 /usr/bin/cmake -E cmake_link_script CMakeFiles/cli.dir/link.txt --verbose=1
#7 52.36 /usr/bin/c++ -O3 -O3 -DNDEBUG -rdynamic -Wl,-Bsymbolic,-znoexecstack -Wl,--dependency-file=CMakeFiles/cli.dir/link.d CMakeFiles/cli.dir/input/input.cpp.o CMakeFiles/cli.dir/input/y4m.cpp.o CMakeFiles/cli.dir/input/yuv.cpp.o CMakeFiles/cli.dir/output/output.cpp.o CMakeFiles/cli.dir/output/raw.cpp.o CMakeFiles/cli.dir/output/reconplay.cpp.o CMakeFiles/cli.dir/output/y4m.cpp.o CMakeFiles/cli.dir/output/yuv.cpp.o CMakeFiles/cli.dir/x265.cpp.o CMakeFiles/cli.dir/x265cli.cpp.o CMakeFiles/cli.dir/abrEncApp.cpp.o -o x265  -Wl,-rpath,/x265/build-release: libx265.so.192 -lpthread -lrt -ldl
#7 52.36 gmake[2]: Leaving directory '/x265/build-release'
#7 52.37 [ 98%] Built target cli
#7 55.20 [100%] Linking CXX executable TestBench
#7 55.20 cd /x265/build-release/test && /usr/bin/cmake -E cmake_link_script CMakeFiles/TestBench.dir/link.txt --verbose=1
#7 55.32 /usr/bin/c++ -O3 -O3 -DNDEBUG -rdynamic -Wl,-Bsymbolic,-znoexecstack -Wl,--dependency-file=CMakeFiles/TestBench.dir/link.d CMakeFiles/TestBench.dir/testbench.cpp.o CMakeFiles/TestBench.dir/pixelharness.cpp.o CMakeFiles/TestBench.dir/mbdstharness.cpp.o CMakeFiles/TestBench.dir/ipfilterharness.cpp.o CMakeFiles/TestBench.dir/intrapredharness.cpp.o -o TestBench  ../libx265.a -lpthread -lrt -ldl
#7 55.32 gmake[2]: Leaving directory '/x265/build-release'
#7 55.33 [100%] Built target TestBench
#7 55.33 gmake[1]: Leaving directory '/x265/build-release'
#7 55.33 /usr/bin/cmake -E cmake_progress_start /x265/build-release/CMakeFiles 0
#7 55.35 
#7 55.36 -- Install configuration: "Release"
#7 55.36 -- Installing: /usr/local/lib/libx265.a
#7 55.36 -- Installing: /usr/local/include/x265.h
#7 55.36 -- Installing: /usr/local/include/x265_config.h
#7 55.36 -- Installing: /usr/local/lib/libx265.so.192
#7 55.37 -- Installing: /usr/local/lib/libx265.so
#7 55.37 -- Installing: /usr/local/lib/pkgconfig/x265.pc
#7 55.37 -- Installing: /usr/local/bin/x265
#7 55.37 -- Set non-toolchain portion of runtime path of "/usr/local/bin/x265" to ""
#7 DONE 55.4s

#8 [5/6] RUN echo /usr/local/lib > /etc/ld.so.conf.d/x265.conf && ldconfig &&     x265 --version 2>&1 | grep -F "HEVC encoder version 3.4"
#8 0.223 x265 [info]: HEVC encoder version 3.4
#8 DONE 0.2s

#9 [6/6] WORKDIR /workspace
#9 DONE 0.0s

#10 exporting to docker image format
#10 exporting layers
#10 exporting layers 22.1s done
#10 exporting manifest sha256:80a300ed3fd86d244ee115a39e85b1180c6ebe682554a65f11f9364d00854f12 0.0s done
#10 exporting config sha256:6b5bd68487b7976971ab31c6a0dfed2f6e25ee4b18c943781e7eec3eee0da8cc 0.0s done
#10 sending tarball
#10 ...

#11 importing to docker
#11 loading layer 3d9680f227f2 557.06kB / 183.47MB
#11 loading layer 3d9680f227f2 103.61MB / 183.47MB 2.1s
#11 loading layer 3d9680f227f2 174.36MB / 183.47MB 4.1s
#11 loading layer 94ac7517b00d 32.77kB / 1.51MB
#11 loading layer 1fb1a1b95541 98.30kB / 7.14MB
#11 loading layer 102c326a0281 6.54kB / 6.54kB
#11 loading layer 3d9680f227f2 174.36MB / 183.47MB 5.0s done
#11 loading layer 94ac7517b00d 32.77kB / 1.51MB 0.4s done
#11 loading layer 1fb1a1b95541 98.30kB / 7.14MB 0.2s done
#11 loading layer 102c326a0281 6.54kB / 6.54kB 0.1s done
#11 loading layer f3129541d9e6 99B / 99B 0.0s done
#11 DONE 5.0s

#10 exporting to docker image format
#10 sending tarball 6.3s done
#10 DONE 28.4s

#12 exporting cache to client directory
#12 preparing build cache for export 0.0s done
#12 sending cache export
#12 writing layer sha256:3a757e322d49a094953b7b35101a4af7e1563330d657916756774d7f147d3438
#12 writing layer sha256:283c34f82a2d511e751b71908e43d304a94ba9ad52bbd1a6c9850d4df23a4400
#12 writing layer sha256:29e1ff4aaab0f13bd525efed3eec4278134eba47857f65f751a3b59af64c299a
#12 writing layer sha256:0c3f823b61e8d2c667cb9d5780e46c5bf61f845c2ef13e92cd3ccba1151c3fc3 0.0s done
#12 writing layer sha256:5eef2c1f4460bd899ade0cc8f5b79a8f6afebd9261b0ac70bddc22e6e51820a0
#12 writing layer sha256:3a757e322d49a094953b7b35101a4af7e1563330d657916756774d7f147d3438 0.0s done
#12 writing layer sha256:29e1ff4aaab0f13bd525efed3eec4278134eba47857f65f751a3b59af64c299a 0.1s done
#12 writing layer sha256:5eef2c1f4460bd899ade0cc8f5b79a8f6afebd9261b0ac70bddc22e6e51820a0 0.0s done
#12 writing layer sha256:b53f1a34af8e951a8e22d5c7b048bac6f2308bb2fcee0b5eb7eb56ad1958c775 0.0s done
#12 writing layer sha256:fcdc6e001144db9419c8eca0f9bd19d13c5ff8d38a087aa1022299656e5995cf
#12 writing layer sha256:283c34f82a2d511e751b71908e43d304a94ba9ad52bbd1a6c9850d4df23a4400 0.7s done
#12 writing layer sha256:fcdc6e001144db9419c8eca0f9bd19d13c5ff8d38a087aa1022299656e5995cf 1.5s done
#12 sending cache export 1.6s done
#12 writing config sha256:2e3b4d71885690128b926565c9365f48fb0d0d27a5d1beb00573b5d54650d463 0.0s done
#12 writing cache image manifest sha256:2a12442d2c188aa88440648ce9558a165fa52a8274714f0acea9b68b40b70175 0.0s done
#12 DONE 1.6s
WARNING: local cache import at /home/oe_fix/actions-runner/_work/openeuler-docker-autopilot/ci-fix-buildkit-cache not found due to err: could not read /home/oe_fix/actions-runner/_work/openeuler-docker-autopilot/ci-fix-buildkit-cache/index.json: open /home/oe_fix/actions-runner/_work/openeuler-docker-autopilot/ci-fix-buildkit-cache/index.json: no such file or directory
