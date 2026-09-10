# DayTrader7 Workload Test

Avocado test that automates the download, installation, and execution of the
DayTrader7 benchmark on IBM Power (ppc64le) systems.

---

## Supported Platforms

Architecture: **ppc64le only** (SLES and RHEL)

---

## System Requirements

| Resource | Minimum                                         |
|----------|-------------------------------------------------|
| Disk     | 100 GB SSD (**must be SSD**, not spinning disk) |
| CPU      | 1 core                                          |
| RAM      | 4 GB                                            |
| User     | root                                            |
| Hostname | FQDN that resolves to the machine IP            |

> DB2 instance creation will fail if the hostname is not a FQDN:
> ```
> hostname <your.fqdn.example.com>
> echo "<your.fqdn.example.com>" > /etc/hostname
> ```

---

## Prerequisites

All required OS packages are installed automatically by the test.
On RHEL, Java 17 packages are detected at runtime from enabled repos.
If not found, the test continues with a warning.

> The AppStream repo name required for Java 17 is printed in the warning
> message at runtime: `<distro>-<version>-for-<arch>-appstream-rpms`.

---

## Install Kit Layout

`install_url` must point to an HTTP directory containing:

```
power_dt7_<distro>_install/
├── DayTrader7_<distro>.tar.gz
├── INSTALL_<distro>.sh
└── dt7_uninstall.sh
```

---

## Configuration (YAML)

Edit `Daytrader.py.data/daytrader.yaml`:

```yaml
install_url: 'http://<server>/path/to/power_dt7_install/'
users: 40
duration: 1800
instances: 2
```

---

## Running the Test

```bash
avocado run Daytrader.py --mux-yaml Daytrader.py.data/daytrader.yaml
```

---

## Files

| File                               | Description             |
|------------------------------------|-------------------------|
| `Daytrader.py`                     | Avocado test            |
| `Daytrader.py.data/daytrader.yaml` | Workload configuration  |
| `Daytrader.py.data/README.md`      | This file               |

