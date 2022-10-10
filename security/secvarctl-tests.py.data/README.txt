secvarctl: set of tools to create and edit secure boot variables on IBM POWER
systems.
More details can be found at https://github.com/open-power/secvarctl

To run the test cases:
change the directory to 'test' with openssl enabled and run 'make OPENSSL=1'.
If command 'make' used to run the test cases then default cryptolibrary used is
'mbedtls'. This 'mbedtls' library not supported/available on distributions,
so using 'OpenSSL' for testing the secvarctl tool.
