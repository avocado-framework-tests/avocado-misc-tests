#!/usr/bin/env python
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
# Copyright: 2026 IBM
# Author: Krishan Gopal Saraswat <krishang@linux.ibm.com>

import os
import platform
import re
import shutil
import subprocess
import threading
from avocado import Test
from avocado.utils import archive, build, distro, git, process
from avocado.utils.software_manager.manager import SoftwareManager

class GrubUnitTest(Test):
    """
    GNU GRUB distro source test suite for PowerPC.
    Fetches the distro grub2 source, builds, and runs make check.
    """

    _ANSI_ESC = re.compile(r'\x1b\[[0-9;]*m')

    # Tests that are not applicable on powerpc-ieee1275
    _NOT_PPC_TESTS = {
        'ahci_test':               'AHCI not present on powerpc-ieee1275 QEMU',
        'ehci_test':               'EHCI not present on powerpc-ieee1275 QEMU',
        'ohci_test':               'OHCI not present on powerpc-ieee1275 QEMU',
        'uhci_test':               'UHCI not present on powerpc-ieee1275 QEMU',
        'pata_test':               'no ATA/PATA driver for powerpc-ieee1275',
        'fddboot_test':            'powerpc-ieee1275 does not support floppy boot',
        'serial_test':             'ieee1275 uses OpenFirmware console, not PCI serial',
        'partmap_test':            'exits 77 detecting live OF disk on powerpc-ieee1275',
        'netboot_test':            'PXE netboot not supported on powerpc-ieee1275 QEMU',
        'tpm2_key_protector_test': 'requires grub-emu; powerpc-ieee1275 uses qemu-system-ppc',
        'minixfs_test':            'minix kernel module absent on ppc64le',
        'erofs_test':              'erofs UUID endian mismatch on ppc64le (blkid vs GRUB)',
        'grub_func_test':          'videotest_checksum pixel values are x86-specific',
        'grub_cmd_cryptomount':    'QEMU mac99 single IDE bus conflict with grub.iso',
        # Filesystem tests that require tools absent on ppc64le distros
        'hfs_test':                'mkfs.hfs (hfsprogs) not available on ppc64le',
        'hfsplus_test':            'mkfs.hfsplus (hfsprogs) not available on ppc64le',
        'reiserfs_test':           'mkfs.reiserfs (reiserfsprogs) not available on ppc64le',
        'btrfs_test':              'mkfs.btrfs (btrfs-progs) not available on ppc64le RHEL/SLES CI',
        'f2fs_test':               'mkfs.f2fs (f2fs-tools) not available on ppc64le',
        'nilfs2_test':             'mkfs.nilfs2 (nilfs-utils) not available on ppc64le',
        'zfs_test':                'ZFS kernel module not available on ppc64le RHEL/SLES',
        'zfs_zstd_test':           'ZFS kernel module not available on ppc64le RHEL/SLES',
        'jfs_test':                'mkfs.jfs (jfsutils) not available on ppc64le RHEL',
        'romfs_test':              'genromfs not available on ppc64le RHEL/SLES',
    }

    _SLOW_TESTS = [
        ('luks2_test',   60,  True),
        ('pseries_test', 60,  True),
        ('fat_test',     900, False),
    ]

    _PARALLEL_FS_TESTS = [
        ('fat_test',      ['vfat16a', 'vfat12a', 'vfat12', 'vfat16', 'vfat32']),
        ('squashfs_test', ['squash4_gzip', 'squash4_xz', 'squash4_lzo']),
        ('ext234_test',   ['ext2_old', 'ext2', 'ext3', 'ext4', 'ext4_metabg', 'ext4_encrypt']),
        ('ntfs_test',     ['ntfs', 'ntfscomp']),
    ]

    def setUp(self):
        '''
        Install all required dependencies and fetch distro GRUB source.
        '''
        if 'ppc' not in platform.machine():
            self.cancel('Test requires PowerPC (detected: %s)' % platform.machine())

        smm = SoftwareManager()
        detected_distro = distro.detect()
        self.test_type = self.params.get('test_type', default='unit')

        is_rhel = detected_distro.name in ('rhel', 'redhat')
        is_suse = 'SuSE' in detected_distro.name or 'suse' in (detected_distro.name or '').lower()
        rhel_ver = int(str(detected_distro.version or '0').split('.')[0])

        qemu_ok = self._qemu_present()
        deps = ['gcc', 'gcc-c++', 'make', 'automake', 'autoconf', 'bison', 'flex',
                'python3', 'help2man', 'rsync', 'patch', 'parted',
                'device-mapper-devel', 'xz-devel', 'fuse-devel']
        if is_suse:
            deps += ['git-core', 'gettext-tools', 'freetype2-devel',
                     'dejavu-fonts', 'xorriso', 'qemu-ppc', 'grub2-common']
            if self.test_type in ('shell', 'fs') and not qemu_ok:
                deps += ['ninja', 'meson', 'glib2-devel', 'libpixman-1-0-devel',
                         'zlib-devel', 'libslirp-devel']
            if self.test_type == 'fs':
                deps += ['e2fsprogs', 'xfsprogs', 'dosfstools',
                         'cryptsetup', 'exfatprogs',
                         'libselinux-devel', 'libtool', 'libgcrypt-devel',
                         'squashfs', 'liblz4-devel', 'libuuid-devel',
                         'jfsutils', 'xorriso', 'lzop']
        elif is_rhel:
            deps += ['git', 'gettext', 'gettext-devel',
                     'freetype-devel', 'dejavu-sans-fonts',
                     'xorriso', 'grub2-common']
            if self.test_type in ('shell', 'fs') and not qemu_ok:
                deps += ['ninja-build', 'meson', 'glib2-devel', 'pixman-devel',
                         'zlib-devel', 'libslirp-devel']
                if rhel_ver < 10:
                    deps.append('python3-tomli')
            if self.test_type == 'fs':
                deps += ['e2fsprogs', 'xfsprogs', 'dosfstools',
                         'cryptsetup', 'exfatprogs',
                         'libselinux-devel', 'libtool', 'libgcrypt-devel',
                         'squashfs-tools', 'lz4-devel']
                if rhel_ver < 10:
                    deps += ['genisoimage', 'udftools']
        else:
            deps += ['g++', 'git']

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        if self.test_type == 'fs':
            soft = []
            if is_suse:
                soft += ['udftools', 'mkisofs']
            elif is_rhel:
                soft += ['lzop']
                if rhel_ver >= 10:
                    soft += ['udftools']
            for pkg in soft:
                if not smm.check_installed(pkg) and not smm.install(pkg):
                    self.log.warning('%s unavailable; dependent test will SKIP' % pkg)

        if is_suse and self.test_type == 'fs':
            words_path = '/usr/share/dict/linux.words'
            cracklib_pwd = '/usr/share/cracklib/pw_dict.pwd'
            if not os.path.exists(words_path) and os.path.exists(cracklib_pwd):
                os.makedirs('/usr/share/dict', exist_ok=True)
                try:
                    os.symlink(cracklib_pwd, words_path)
                except OSError as exc:
                    self.log.warning('Could not create words symlink: %s' % exc)

        self.smm = smm
        self._ensure_qemu()

        if self.test_type == 'fs':
            self._ensure_erofs_utils()
            self._ensure_ntfs3g()

        try:
            max_loop_path = '/sys/module/loop/parameters/max_loop'
            if os.path.exists(max_loop_path):
                with open(max_loop_path) as fh:
                    cur = int(fh.read().strip())
                if cur < 64:
                    process.run('modprobe loop max_loop=64 || '
                                'echo 64 > %s' % max_loop_path,
                                shell=True, ignore_status=True)
        except (OSError, ValueError):
            pass

        self.srcdir = os.path.join(self.workdir, 'grub-distro')
        grub_url = self.params.get(
            'grub_url',
            default='https://git.savannah.gnu.org/git/grub.git')
        cache_dir = '/var/tmp/grub-unit-tests-cache'
        ncpus = os.cpu_count() or 1

        # Attempt a full upstream build; fall back to a pre-built cache on any
        # network/build failure (e.g. Savannah gnulib HTTP 500 during bootstrap).
        built_from_source = False
        build_error = None
        try:
            git.get_repo(grub_url, destination_dir=self.srcdir)
            os.chdir(self.srcdir)
            if process.run('./bootstrap --skip-po',
                           ignore_status=True).exit_status:
                raise RuntimeError('grub bootstrap failed')
            if process.run('./configure --with-platform=ieee1275',
                           ignore_status=True).exit_status:
                raise RuntimeError('grub configure failed')
            if build.make(self.srcdir, extra_args='-j%d' % ncpus,
                          process_kwargs={'ignore_status': True}):
                raise RuntimeError('grub make failed')
            built_from_source = True
        except Exception as exc:  # pylint: disable=broad-except
            build_error = exc
            self.log.warning('upstream build failed (%s); trying cache at %s'
                             % (exc, cache_dir))

        if built_from_source:
            # Persist a fresh build to the cache for future fallback use.
            try:
                if os.path.isdir(cache_dir):
                    shutil.rmtree(cache_dir)
                shutil.copytree(self.srcdir, cache_dir,
                                symlinks=True, ignore_dangling_symlinks=True)
                self.log.info('Updated grub build cache at %s' % cache_dir)
            except Exception:  # pylint: disable=broad-except
                pass
        else:
            # Upstream build failed — reuse cached build.
            if not os.path.isdir(cache_dir):
                self.cancel('upstream build failed (%s) and no cache at %s'
                            % (build_error, cache_dir))
            self.log.info('Using cached GRUB build from %s' % cache_dir)
            # Clean any partial clone/build before rsyncing.
            if os.path.isdir(self.srcdir):
                shutil.rmtree(self.srcdir)
            if process.run(
                    'rsync -a %s/ %s/' % (cache_dir, self.srcdir),
                    shell=True, ignore_status=True).exit_status:
                self.cancel('Failed to rsync grub cache to workdir')
            # Re-run make so binaries reference the correct workdir paths.
            os.chdir(self.srcdir)
            if build.make(self.srcdir, extra_args='-j%d' % ncpus,
                          process_kwargs={'ignore_status': True}):
                self.fail('grub make (from cache) failed')

        if self.test_type == 'fs':
            self._check_kernel_modules()

        self._setup_grub_mkfont_compat()
        self._setup_unicode_font()

        self._patch_grub_fs_tester()
        for script, subtests in self._PARALLEL_FS_TESTS:
            self._patch_test_parallel(script, subtests)

    def _patch_file(self, path, old, new):
        """Replace old with new in path."""
        try:
            with open(path, 'r') as fh:
                content = fh.read()
            if old not in content:
                return False
            with open(path, 'w') as fh:
                fh.write(content.replace(old, new, 1))
            return True
        except OSError:
            return False

    def _patch_grub_fs_tester(self):
        for path in (os.path.join(self.srcdir, 'grub-fs-tester.in'),
                     os.path.join(self.srcdir, 'grub-fs-tester')):
            self._patch_file(path, 'MOUNTFS="exfat-fuse"', 'MOUNTFS="exfat"')
            self._patch_file(path,
                             '(cd "$MASTER"; tar cf "${FSIMAGEP}0.img" .)',
                             '(cd "$MASTER"; tar --format=gnu -cf "${FSIMAGEP}0.img" .)')

    def _patch_test_parallel(self, script_name, subtests):
        sentinel = '_%s_parallel_patched' % script_name
        parallel_body = (
            '# %s\n_pids=\nfor _sub in %s; do\n'
            '    "%%s/grub-fs-tester" "$_sub" &\n'
            '    _pids="$_pids $!"\ndone\n'
            '_rc=0\nfor _pid in $_pids; do\n'
            '    wait "$_pid" || _rc=$?\ndone\n'
            '[ "$_rc" -eq 0 ] || exit "$_rc"\n'
        ) % (sentinel, ' '.join(subtests))

        in_file = os.path.join(self.srcdir, 'tests', '%s.in' % script_name)
        if os.path.isfile(in_file):
            old = ''.join('"@builddir@/grub-fs-tester" %s\n' % s for s in subtests)
            with open(in_file) as fh:
                already = sentinel in fh.read()
            if not already and self._patch_file(in_file, old, parallel_body % '@builddir@'):
                process.run('cd %s && make %s' % (self.srcdir, script_name),
                             shell=True, ignore_status=True)
                return

        script = os.path.join(self.srcdir, script_name)
        if os.path.isfile(script):
            with open(script) as fh:
                already = sentinel in fh.read()
            if not already:
                old = ''.join('"./grub-fs-tester" %s\n' % s for s in subtests)
                self._patch_file(script, old, parallel_body % '.')

    @staticmethod
    def _qemu_present():
        return (
            process.system('which qemu-system-ppc', ignore_status=True) == 0 and
            process.system('which qemu-system-ppc64', ignore_status=True) == 0
        )

    def _setup_grub_mkfont_compat(self):
        link = '/usr/local/bin/grub-mkfont'
        if os.path.exists(link):
            return
        for src in ('/usr/bin/grub2-mkfont', '/usr/sbin/grub2-mkfont',
                    '/usr/local/bin/grub2-mkfont'):
            if os.path.exists(src):
                try:
                    os.symlink(src, link)
                except OSError:
                    pass
                break

    def _build_from_tarball(self, name, src, configure_args, pre_configure=None):
        """Configure, build and install a source tree."""
        ncpus = os.cpu_count() or 1
        os.chdir(src)
        if pre_configure:
            if process.run(pre_configure, ignore_status=True).exit_status:
                self.fail('%s %s failed' % (name, pre_configure))
        if process.run('./configure %s' % configure_args,
                       ignore_status=True).exit_status:
            self.fail('%s configure failed' % name)
        if build.make(src, extra_args='-j%d' % ncpus,
                      process_kwargs={'ignore_status': True}):
            self.fail('%s make failed' % name)
        if process.system('make install', ignore_status=True):
            self.fail('%s make install failed' % name)

    def _fetch_and_build(self, name, url, version, prefix, pre_configure=None):
        """Fetch a tarball asset, extract it, build and install it."""
        tarball = self.fetch_asset(url, expire='30d')
        src = os.path.join(self.workdir, '%s-%s' % (name, version))
        archive.extract(tarball, self.workdir)
        self._build_from_tarball(name, src, '--prefix=/usr/local' + (
            ' ' + prefix if prefix else ''), pre_configure)
        process.system('ldconfig', ignore_status=True)

    def _ensure_qemu(self):
        if self._qemu_present():
            for name in ('qemu-system-ppc', 'qemu-system-ppc64'):
                link = '/usr/local/bin/%s' % name
                if not os.path.exists(link):
                    target = shutil.which(name)
                    if target:
                        try:
                            os.symlink(target, link)
                        except OSError:
                            pass
            return

        qemu_url = self.params.get(
            'qemu_url',
            default='https://download.qemu.org/qemu-9.2.3.tar.xz')
        qemu_version = self.params.get('qemu_version', default='9.2.3')
        tarball = self.fetch_asset(qemu_url, expire='30d')
        src = os.path.join(self.workdir, 'qemu-%s' % qemu_version)
        archive.extract(tarball, self.workdir)
        self._build_from_tarball(
            'QEMU', src,
            '--target-list=ppc-softmmu,ppc64-softmmu '
            '--prefix=/usr/local --disable-docs --disable-werror')

    def _ensure_erofs_utils(self):
        if process.system('which mkfs.erofs', ignore_status=True) == 0:
            return
        self._fetch_and_build(
            'erofs-utils',
            self.params.get('erofs_utils_url', default=(
                'https://github.com/erofs/erofs-utils/archive/refs/tags/v1.8.1.tar.gz')),
            self.params.get('erofs_utils_version', default='1.8.1'),
            '', './autogen.sh')

    def _ensure_ntfs3g(self):
        if process.system('which mkfs.ntfs', ignore_status=True) == 0:
            return
        self._fetch_and_build(
            'ntfs-3g',
            self.params.get('ntfs3g_url', default=(
                'https://github.com/tuxera/ntfs-3g/archive/refs/tags/2022.10.3.tar.gz')),
            self.params.get('ntfs3g_version', default='2022.10.3'),
            '--disable-static --with-fuse=external', 'autoreconf -fiv')
        if process.system('which mkfs.ntfs', ignore_status=True) != 0:
            process.system(
                'ln -sf /usr/local/sbin/mkntfs /usr/local/sbin/mkfs.ntfs',
                ignore_status=True)

    def _setup_unicode_font(self):
        pf2 = os.path.join(self.srcdir, 'unicode.pf2')
        if os.path.isfile(pf2) and not os.path.islink(pf2):
            return
        if os.path.exists(pf2):
            return
        for candidate in ('/usr/share/grub/unicode.pf2',
                          '/usr/share/grub2/unicode.pf2',
                          '/boot/grub/fonts/unicode.pf2',
                          '/boot/grub2/fonts/unicode.pf2'):
            if os.path.exists(candidate):
                os.symlink(candidate, pf2)
                return
        self.cancel('unicode.pf2 not found; install grub2-common')

    def _check_kernel_modules(self):
        for mod in ('minix', 'f2fs'):
            if process.run('modinfo %s' % mod, ignore_status=True).exit_status != 0:
                self.log.warning('%s module absent; %s_test will SKIP' % (mod, mod))

    def test(self):
        '''
        Run the GRUB test suite.
        Tests not applicable to powerpc are skipped.
        '''
        ncpus = os.cpu_count() or 1
        suite_timeout = int(self.params.get('suite_timeout', default='7200') or '7200')
        slow_timeout = int(
            self.params.get('slow_test_timeout', default='60') or '60')

        slow_tests = [(name, slow_timeout if default_t == 0 else default_t, is_skip)
                      for name, default_t, is_skip in self._SLOW_TESTS]

        env = os.environ.copy()
        env['PATH'] = '/usr/local/sbin:/usr/local/bin:' + env.get('PATH', '')
        env['TZ'] = 'UTC'

        os.chdir(self.srcdir)

        all_tests = [
            str(t) for t in str(process.run(
                "make --eval='_lt: ; @echo $(TESTS)' _lt",
                shell=True, env=env, ignore_status=True,
            ).stdout_text).split()
            if t and not str(t).startswith('make')
        ]

        slow_names = {n for n, _, _ in slow_tests}
        ppc_skip = {n: r for n, r in self._NOT_PPC_TESTS.items() if n in all_tests}
        for name, reason in ppc_skip.items():
            self.log.info('SKIP [not-ppc]: %s -- not related to powerpc -- %s' % (name, reason))

        fast_tests = [t for t in all_tests
                      if t not in slow_names and t not in ppc_skip]

        fast_out = process.run(
            'setsid timeout %d make check -j%d -k TESTS="%s" </dev/null 2>&1'
            % (suite_timeout, ncpus, ' '.join(fast_tests)),
            shell=True, env=env, ignore_status=True)

        timed_out = (fast_out.exit_status == 124)

        slow_results = {}
        lock = threading.Lock()

        def _run_slow(name, timeout, skip_on_timeout):
            log = os.path.join(self.srcdir, 'test-suite-%s.log' % name)
            ret = subprocess.call(
                'setsid timeout %d make check TESTS="%s" </dev/null >%s 2>&1'
                % (timeout, name, log),
                shell=True, env=env, cwd=self.srcdir, stdin=subprocess.DEVNULL)
            try:
                with open(log, errors='replace') as fh:
                    text = fh.read()
            except OSError:
                text = ''
            if ret == 124:
                result = 'SKIP' if skip_on_timeout else 'TIMEOUT'
            else:
                result = 'SKIP'
                for line in text.splitlines():
                    s = self._ANSI_ESC.sub('', str(line)).strip()
                    for tag in ('PASS', 'FAIL', 'ERROR', 'SKIP'):
                        if s.startswith(tag + ': ' + name):
                            result = tag
                            break
                    else:
                        continue
                    break
            with lock:
                slow_results[name] = result

        threads = [threading.Thread(target=_run_slow, args=a, daemon=True)
                   for a in slow_tests]
        for t in threads:
            t.start()
        max_slow = max(t for _, t, _ in slow_tests)
        for t in threads:
            t.join(timeout=max_slow + 30)
        with lock:
            for name, _, skip_on_timeout in slow_tests:
                if name not in slow_results:
                    slow_results[name] = 'SKIP' if skip_on_timeout else 'TIMEOUT'

        pass_l, fail_l, skip_l, timeout_l = [], [], [], []
        reported = set()
        for line in str(fast_out.stdout_text).splitlines():
            s = self._ANSI_ESC.sub('', line).strip()
            for tag, lst in (('PASS: ', pass_l), ('SKIP: ', skip_l),
                             ('FAIL: ', fail_l)):
                if s.startswith(tag):
                    name = s[len(tag):]
                    lst.append(name)
                    reported.add(name)
                    break
            else:
                if s.startswith('ERROR: '):
                    name = s[7:]
                    skip_l.append(name)
                    reported.add(name)

        if timed_out:
            timeout_l.extend(t for t in fast_tests if t not in reported)

        for name, result in slow_results.items():
            reported.add(name)
            {'PASS': pass_l, 'FAIL': fail_l, 'TIMEOUT': timeout_l,
             'ERROR': skip_l}.get(result, skip_l).append(name)

        sep = '-' * 60
        self.log.info(sep)
        self.log.info('GRUB test results [test_type=%s]' % self.test_type)
        self.log.info(sep)
        for t in sorted(pass_l):
            self.log.info('  PASS:  %s' % t)
        for t in sorted(skip_l):
            self.log.info('  SKIP:  %s' % t)
        for name, reason in sorted(ppc_skip.items()):
            self.log.info('  SKIP [not-ppc]: %-30s (%s)' % (name, reason))
        for t in sorted(fail_l):
            self.log.warning('  FAIL:  %s' % t)
        for t in sorted(timeout_l):
            self.log.error('  TIMEOUT: %s' % t)
        self.log.info(sep)
        self.log.info(
            'TOTAL %d  PASS %d  SKIP %d  NOT-PPC %d  FAIL %d  TIMEOUT %d'
            % (len(pass_l) + len(skip_l) + len(ppc_skip) +
               len(fail_l) + len(timeout_l),
               len(pass_l), len(skip_l), len(ppc_skip),
               len(fail_l), len(timeout_l)))
        self.log.info(sep)

        if fail_l or timeout_l:
            self.fail('%d FAILED  %d TIMEOUT' % (len(fail_l), len(timeout_l)))
