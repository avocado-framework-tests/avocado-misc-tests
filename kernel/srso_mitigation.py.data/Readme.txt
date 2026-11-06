This is a mitigation for the speculative return stack overflow (SRSO)
vulnerability found on AMD processors. The mechanism is by now the
well known scenario of poisoning CPU functional units - the Branch
Target Buffer (BTB) and Return Address Predictor (RAP) in this
case - and then tricking the elevated privilege domain (the kernel)
into leaking sensitive data.

AMD CPUs predict RET instructions using a Return Address Predictor
(aka Return Address Stack/Return Stack Buffer). In some cases, a
non-architectural CALL instruction (i.e., an instruction predicted
to be a CALL but is not actually a CALL) can create an entry in the
RAP which may be used to predict the target of a subsequent RET
instruction.

The specific circumstances that lead to this varies by
microarchitecture but the concern is that an attacker can mis-train
the CPU BTB to predict non-architectural CALL instructions in kernel
space and use this to control the speculative target of a subsequent
kernel RET, potentially leading to information disclosure via a
speculative side-channel.

Here, we test if the processor is mitigated from the vulnerability.

1. SRSO Selftest available as a part of kernel source code.
We run the selftest available at tools/testing/selftest/x86/srso.c
2. Check the sysfs for vulnerability status.

Ref: https://docs.kernel.org/admin-guide/hw-vuln/srso.html

Parameters:

url: The url for selftest srso.c
