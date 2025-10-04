#include <stdio.h>
#include <linux/vfio.h>

#define print_ioctl(value) printf(#value " %d\n", value)

int main() {
    print_ioctl(VFIO_GROUP_GET_STATUS);
    print_ioctl(VFIO_GROUP_GET_DEVICE_FD);
    print_ioctl(VFIO_DEVICE_GET_IRQ_INFO);
    print_ioctl(VFIO_DEVICE_SET_IRQS);
    print_ioctl(VFIO_IRQ_SET_ACTION_TRIGGER);
    print_ioctl(VFIO_GROUP_FLAGS_VIABLE);
    print_ioctl(VFIO_GROUP_SET_CONTAINER);
    print_ioctl(VFIO_GET_API_VERSION);
    print_ioctl(VFIO_API_VERSION);
    print_ioctl(VFIO_CHECK_EXTENSION);
    print_ioctl(VFIO_TYPE1_IOMMU);
    print_ioctl(VFIO_SET_IOMMU);
    print_ioctl(VFIO_IRQ_SET_DATA_EVENTFD);
    print_ioctl(VFIO_DEVICE_RESET);
    print_ioctl(VFIO_PCI_MSIX_IRQ_INDEX);
    print_ioctl(VFIO_IRQ_INFO_EVENTFD);
    print_ioctl(VFIO_GROUP_UNSET_CONTAINER);
    return 0;
}
