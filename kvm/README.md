# KVM Unit Tests

The KVM unit tests are designed to provide functional testing for the Kernel-based Virtual Machine (KVM) by targeting specific features through minimal implementations.

This is an avocado wrapper to run KVM unit tests. It leverages the Avocado testing framework to provide a structured environment for executing KVM unit tests.

## Parameters
### Inputs
**test**: List of KVM unit tests to run. By default, all tests will be run.<br>
**mode**: Specifies whether to run in accelerated or non-accelerated mode. Default: None<br>
**configure_args**: Specify the additional options to pass to the ./configure script. These may include settings for architecture, compiler, or -cross-compilation prefixes (eg. ./configure --cc=clang).<br>
**kvm_module**: Detects the KVM kernel module to use (e.g., kvm_amd for AMD or kvm_intel for Intel).<br>
**kvm_module_param**: Specify the KVM module parameter to use (e.g., avic or nested).<br>
**qemu_binary**: Path to a custom QEMU binary to use for running the tests (ex. /usr/bin/qemu-system-x86_64)<br>
**accelerator**: Specifies the CPU accelerator (e.g., kvm, hvf, or tcg) by setting the ACCEL environment variable before running the test.

### Sample YAML to pass test's parameters

cat ../kvm_unittest.py.data/kvm_unittest.yaml
```
test: !mux
  memory:
    test: memory
  x2apic_non_accelerated:
    test: x2apic
    mode: non-accelerated
  x2apic_accelerated:
    test: x2apic
    mode: accelerated
```

# References:
[KVM Unit Tests Documentation](https://www.linux-kvm.org/page/KVM-unit-tests)<br>
