fortdepend -f src/**/*.f90 -g -o deps.svg \
  -i netcdf mo_netcdf datetime_module omp_lib resultmodule errorinstancemodule errorcriteriamodule spoof

fortdepend -f src/**/*.f90 vendor/**/*.f90 -g -o deps.svg \
  -i omp_lib netcdf spoof