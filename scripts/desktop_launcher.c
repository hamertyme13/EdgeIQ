#include <stdio.h>
#include <unistd.h>

#ifndef EDGEIQ_LAUNCHER_PATH
#error "EDGEIQ_LAUNCHER_PATH must point to launch_edgeiq.sh"
#endif

int main(void) {
    execl("/bin/bash", "bash", EDGEIQ_LAUNCHER_PATH, (char *)NULL);
    perror("EdgeIQ could not start its launcher");
    return 1;
}
