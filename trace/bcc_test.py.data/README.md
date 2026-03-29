# BCC (BPF Compiler Collection) Test

Tests BCC functionality by downloading the source RPM, building it and
running the upstream test suite.

## Supported Distributions

- RHEL / CentOS / Fedora
- SLES 15 SP6, SLES 15 SP7, SLES 16+

## How BCC Source RPM is obtained

| Distribution | Method |
|-------------|--------|
| RHEL / CentOS / Fedora | `dnf --source download bcc`; fallback: auto-discovered from CentOS Stream mirror |
| SLES 16+ | `zypper source-install bcc`; fallback: auto-discovered from openSUSE mirror |
| SLES 15 SP6 and below | `zypper source-install bcc`; fallback: auto-discovered from openSUSE mirror |
| SLES 15 SP7 | `zypper source-install bcc` via IBM FTP ISO mirror; fallback: direct wget from IBM FTP |

## YAML Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `bcc_ftp_user` | Yes (SLES 15 SP7 only) | IBM internal FTP username for ISO mirror access |
| `bcc_ftp_pass` | Yes (SLES 15 SP7 only) | IBM internal FTP password for ISO mirror access |
| `bcc_src_url` | No | Direct URL to bcc src RPM — overrides package manager download (any distro) |

`bcc_src_url` is optional. Use it to provide a direct URL to the bcc source
RPM when the default package manager download is unavailable (e.g. no source
repos, offline lab, custom mirror). Works for any distro.

### Example bcc_test.yaml (SLES 15 SP7)

```yaml
bcc_ftp_user: <username>
bcc_ftp_pass: <password>
```

`bcc_ftp_user` and `bcc_ftp_pass` are IBM internal lab FTP credentials
required to access the SLES 15 SP7 ISO mirror at `ftp3install.linux.ibm.com`.
Contact your lab administrator for the credentials.

##Sles15sp6/Sles15sp7
```bash
avocado run bcc_test.py -m bcc_test.yaml
```

For all other distributions, the YAML file is not required.

## Running

```bash
avocado run bcc_test.py
```
