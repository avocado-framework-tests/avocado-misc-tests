import os
import re
import multiprocessing
import json

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import process
from avocado.utils import build


class Dbench(Test):

    """
    Dbench is a tool to generate I/O workloads to either a filesystem or to a
    networked CIFS or NFS server.
    Dbench is a utility to benchmark a system based on client workload
    profiles.
    """

    def setUp(self):
        '''
        Build Dbench
        Source:
        http://samba.org/ftp/tridge/dbench/dbench-3.04.tar.gz
        '''

        try:
            process.run('which gcc')
        except:
            self.error('gcc is required by this job and is not available on'
                       'the system')

        self.results = []
        data_dir = os.path.abspath(self.datadir)
        tarball = self.fetch_asset(
            'http://samba.org/ftp/tridge/dbench/dbench-3.04.tar.gz')
        archive.extract(tarball, self.srcdir)
        cb_version = os.path.basename(tarball.split('.tar.')[0])
        self.srcdir = os.path.join(self.srcdir, cb_version)
        os.chdir(self.srcdir)
        patch = self.params.get('patch', default='dbench_startup.patch')
        process.system('patch -p1 < %s' % data_dir + '/' + patch, shell=True)
        process.run('./configure')
        build.make(self.srcdir)

    def test(self):
        '''
        Test Execution with necessary args
        '''
        dir = self.params.get('dir', default='.')
        nprocs = self.params.get('nprocs', default=None)
        seconds = self.params.get('seconds', default=60)
        args = self.params.get('args', default='')
        if not nprocs:
            nprocs = multiprocessing.cpu_count()
        loadfile = os.path.join(self.srcdir, 'client.txt')
        cmd = '%s/dbench %s %s -D %s -c %s -t %d' % (self.srcdir, nprocs, args,
                                                     dir, loadfile, seconds)
        process.run(cmd)

        self.results = process.system_output(cmd)
        pattern = re.compile(r"Throughput (.*?) MB/sec (.*?) procs")
        (throughput, procs) = pattern.findall(self.results)[0]
        perf_json = {'throughput': throughput, 'procs': procs}
        output_path = os.path.join(self.outputdir, "perf.json")
        json.dump(perf_json, open(output_path, "w"))

if __name__ == "__main__":
    main()
