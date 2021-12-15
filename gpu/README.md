## READ.md - This readme details on steps to setup CUDA stack on GPU installed System ##
## Follow below steps configure/setup CUDA, depending on cuda support for respective Distro cuda version may vary ##
## Whatever CUDA version specified in the readme works for RHEL-8.x distro only ##

/****************** Setup ***********************/
1.  Check for NVIDIA Volta GPU devices on AC922
[root@ltc-wspoon12 ~]# lspci | grep -i nvidia
0004:04:00.0 3D controller: NVIDIA Corporation GV100GL [Tesla V100 SXM2 32GB] (rev a1)
0004:05:00.0 3D controller: NVIDIA Corporation GV100GL [Tesla V100 SXM2 32GB] (rev a1)
0035:03:00.0 3D controller: NVIDIA Corporation GV100GL [Tesla V100 SXM2 32GB] (rev a1)
0035:04:00.0 3D controller: NVIDIA Corporation GV100GL [Tesla V100 SXM2 32GB] (rev a1)

2. Pre-requisites packages
##os related packages
$ dnf install -y  kernel-devel kernel-headers gcc make gcc-c++ numactl openssh-server wget net-tools libX11-devel mesa-libGLU-devel freeglut-devel

##Setup EPEL repository
$ rpm -Uvh http://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm

3. Install cuda packages(which will have nvidia driver)

wget https://developer.download.nvidia.com/compute/cuda/11.5.1/local_installers/cuda-repo-rhel8-11-5-local-11.5.1_495.29.05-1.ppc64le.rpm
rpm -i cuda-repo-rhel8-11-5-local-11.5.1_495.29.05-1.ppc64le.rpm
dnf clean all
dnf -y module install nvidia-driver:latest-dkms
dnf -y install cuda

4. Start the NVIDIA Persistent Daemon at boot time
$ systemctl enable nvidia-persistenced
$ systemctl start nvidia-persistenced

5. Reboot and post boot check nvidia-smi
$ reboot
$ nvidia-smi
$ lsmod | grpe nividia
[root@ltc-wspoon12 ~]# lsmod | grep -i nvidia
nvidia_drm             83762  0
nvidia_modeset       1426709  1 nvidia_drm
nvidia              40805853  52 nvidia_modeset
drm_kms_helper        377602  5 drm_vram_helper,ast,nvidia_drm
drm                   784787  8 drm_kms_helper,drm_vram_helper,ast,nvidia,drm_ttm_helper,nvidia_drm,ttm

#### EOF - READ.md ####
