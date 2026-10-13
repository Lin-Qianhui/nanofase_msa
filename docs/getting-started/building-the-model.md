
# Building the model

Before running the model, it needs to be compiled into an executable file. There are a number of ways to do this, but all require the following to be installed:
* A modern Fortran compiler, such as GFortran ≥ 7 or Intel Fortran.
* NetCDF Fortran

If you are on Linux or Mac, installing using `apt` or `brew` is easy: `apt install gfortran libnetcdf-dev libnetcdff-dev` or `brew install gcc netcdf`. If you are on Windows, we recommend using Windows Subsystem for Linux (in which case, installation is the same as for Linux using `apt`) or Cygwin (install package `libnetcdf-fortran-devel`).

```{caution}
If your system has multiple versions of GFortran installed, make sure that the NetCDF libraries are compiled using the same compiler version as you compile the NanoFASE model with. Issues can occur if, for instance, you have an older version of GFortran installed that is run using the `gfortran` command, and version 9 installed that is run using `gfortran-9`. `apt` will default to compiling NetCDF using the `gfortran` command, and thus the compiled libraries will not be compatible with NanoFASE model code compiled using `gfortran-9`.
```

## Getting the code

First, get a copy of the code by cloning the repo, making sure to specify `--recurse-submodules` to pull in code for the submodules in the `vendor/` directory:

```console
$ git clone https://github.com/nerc-ceh/nanofase.git --recurse-submodules
$ cd nanofase
```

If you forget the `--recurse-submodule` flag, then run the following from the repo directory:

```console
$ git submodule update --init --recursive
```

## Using fpm (Fortran Package Manager)

The easiest way to build the model is use [fpm](https://fpm.fortran-lang.org/) (Fortran Package Manger). You can install this easily using Conda (`conda install -c conda-forge fpm`). To build the model without installing:

```sh
$ fpm @release
```

```{note}
If you are using Windows PowerShell, the "@" character is a special character and must be escaped using a backtick: `fpm \`@release`.
```


The model binary will be placed in a subdirectory of the `build` folder. The `fpm @run` command can be used to run this executable (see [](./running-the-model)). Alternatively, you can install the model:

```sh
$ fpm @install
```

Optionally, you can provide an install directory using `--prefix <path-to-installation-dir>`, otherwise the model will install to a default location for your system (e.g. `/home/<user>/.local` on Linux)

## Using CMake

The model can also be built using CMake:

```sh
$ mkdir build && cd build
$ cmake ..
$ make
```

After running these commands, a executable file named `nanofase` (`nanofase.exe` on Windows) will be available in the `build` directory. Set `-DCMAKE_BUILD_TYPE=Debug` or `-DCMAKE_BUILD_TYPE=Release` explicitly (e.g. `cmake .. -DCMAKE_BUILD_TYPE=Release`). Unless you are developing the model, use the release version as the model is significantly faster.

```{caution}
Note that, whilst CMake can be used to compile the model using the ifort or ifx compilers (e.g. by using the -DCMAKE_Fortran_COMPILER=ifort flag), issues can arise when the installed version of NetCDF that the CMake script finds isn't a version compiled by an Intel compiler (such as those installed by `apt` and `brew`). Therefore, we recommend compiling using the compiler that your NetCDF installation used. As a workaround, you can explicitly point CMake to the correct version of NetCDF by declaring NETCDF_INCLUDES (include directories) and NETCDF_LIBRARIES_F90 (link libraries) (e.g. by specifying -DNETCDF_INCLUDES=.. -DNETCDF_LIBRARIES_F90=..).
```

## Using Make

The example Makefile delegates to CMake, so install CMake as well as the compiler
and NetCDF. It creates the directories it needs:

```sh
make -f Makefile.example
make -f Makefile.example release
make -f Makefile.example fast
make -f Makefile.example clean
```

Alternatively, copy it with `cp Makefile.example Makefile` and omit `-f`.
The default is Debug. Release uses the existing CMake Release settings; fast uses
GNU Fortran Release with `-Ofast`. The executable is `build/nanofase`, and the
compilation record is `build/comp_meta`. Each mode has its own `build/make-*`
directory; cleaning leaves unrelated builds and fpm caches alone.

Override `BUILD_DIR`, `FC`, `JOBS`, or `MODEL_VERSION` on the command line as needed.
NetCDF is located through `nf-config`, with optional `NETCDF_INCLUDES` and
`NETCDF_LIBRARIES_F90` overrides. Use `CMAKE_ARGS` for additional CMake settings.
Old standalone flag and object-list variables are no longer used.

## Choosing the reported version

CMake and Make use an explicit label when provided, otherwise this checkout's
`git describe --tags`, and finally `0.0.5` when usable Git history is absent.
CMake generates the version module in the build directory and refreshes it before
compilation. It never rewrites tracked source.

```sh
cmake -S . -B build-debug -DCMAKE_BUILD_TYPE=Debug -DNANOFASE_VERSION=0.0.5-18-g163ae42
cmake --build build-debug
make -f Makefile.example MODEL_VERSION=0.0.5-18-g163ae42
```

An empty override returns to automatic selection. fpm, including the package
recipe's `fpm @install`, reads the tracked fallback directly and reports `0.0.5`.
The existing 17-character constant and 16-character model-output limit remain.
Use identical explicit labels and compiler settings when comparing model results.

Main and test programs keep their compiler-generated module files in separate
directories. On upgrading an old CMake build directory, old module files in its
root move to `legacy-fortran-modules` so tests cannot read stale declarations.
Use a separate build directory when upgrading an old in-source build.
