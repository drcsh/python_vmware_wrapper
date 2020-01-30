import time

from pyVmomi import vmodl

from support_functions import task_functions
from const import VM_POWER_STATE_ON
from exceptions import VMWareTimeout, VMWareBadState, VMWareGuestOSException, VMWareGuestOSTimeoutException


def power_on_vm_and_wait_for_os(v_sphere, vmw_vm):
    """
    Does the actual work of powering on a VM, i.e. starting the task, checking it finishes correctly, and then checking
    for vmware tools to become available which means that the os is ready.

    :param v_sphere:
    :param vmw_vm:
    :return:
    """

    v_sphere.logger.info(f"Trying to power on {vmw_vm}")

    task = vmw_vm.PowerOn()
    task_functions.wait_for_task_complete(v_sphere, task, timeout_seconds=60)

    wait_for_vmware_tools_response(v_sphere, vmw_vm)


def power_off_vm_soft(v_sphere, vmw_vm):
    """
    Asks the OS to shut down please, when it is ready.

    Note that VMWare doesn't always return a task for this (shakes fist) so we manually poke the VM to make sure it
    switches off.

    :param VSphere v_sphere:
    :param vim.ManagedObject vmw_vm:
    :return:
    """
    timeout = 240
    task = vmw_vm.ShutdownGuest()

    if task:  # ShutdownGuest doesn't always return a task, which is rather annoying.
        task_functions.wait_for_task_complete(v_sphere, task, timeout_seconds=timeout)

    else:
        # Manually check the VM shut down as requested because VMWare didn't give us a Task.
        time.sleep(20)

        wait_count = 0
        refreshes = 0
        while vmw_vm.summary.runtime.powerState == VM_POWER_STATE_ON:
            time.sleep(5)
            v_sphere.logger.info("VM to shut down, current status {}".format(vmw_vm.guest.toolsRunningStatus))
            wait_count += 1

            # If we waited 2 minutes, try to get a new Managed Object from the Service Instance
            if wait_count > 24:
                # If we've already done this several times times, give up
                if refreshes >= 5:
                    msg = "  VM is still powered on and won't shut off! Help!"
                    v_sphere.logger.error(msg)
                    raise VMWareTimeout(msg)

                v_sphere.logger.info(
                    "Waited 2 minutes for tools. Refreshing VM Object from Service Instance. Might be bugged.")
                vmw_vm = v_sphere.get_vmw_obj_by_uuid(vmw_vm.config.uuid)
                refreshes += 1


def power_off_vm_hard(v_sphere, vmw_vm):
    """
    Tells the host to stop powering the VM. Now.

    :param VSphere v_sphere:
    :param vim.ManagedObject vmw_vm:
    :return:
    """

    task = vmw_vm.PowerOff()
    task_functions.wait_for_task_complete(v_sphere, task, timeout_seconds=60)


def restart_vm_hard(v_sphere, vmw_vm):
    """
    Hard restart the VM (switch power off and on again). Waits for the task to complete.

    :param VSphere v_sphere:
    :param vim.ManagedObject vmw_vm:
    :return:
    """
    task = vmw_vm.ResetVM_Task()
    task_functions.wait_for_task_complete(v_sphere, task, timeout_seconds=30)


def restart_vm_soft_and_wait_for_tools(v_sphere, vmw_vm):
    """
    Soft Reboots VM and calls vmw_vm_check_rebook_ok().

    Many things can go wrong here and we try to paper over the VMWare cracks...

    When sending the reboot command we can encounter an "Invalid Fault", if this happens we wait and try again.

    Once the machine is set rebooting, we call check_reboot_ok(). If this fails for whatever reason we try the whole
    reboot process again up to 5 times.

    note: Because the managed object can screw up, this may tell VSphere to refresh the object.

    :param VSphere v_sphere:
    :param vim.ManagedObject vmw_vm:
    :return:
    """

    if vmw_vm.guest.toolsRunningStatus != "guestToolsRunning":
        msg = "Cannot Reboot: VM is in state: {}".format(vmw_vm.guest.toolsRunningStatus)
        v_sphere.logger.error(msg)
        raise VMWareBadState(msg)

    counter = 0
    check_reboot_exception = None

    while counter < 5:
        try_to_soft_restart(v_sphere, vmw_vm)

        try:
            vmw_vm_check_soft_restarted_ok(v_sphere, vmw_vm)
            return

        except Exception as e:
            check_reboot_exception = e
            counter += 1

    # The exception will only be raised upon exit of the outer loop.
    v_sphere.logger.error("  **  Note: This is the most recent of five exceptions caught: {}".format(
        check_reboot_exception))
    raise VMWareGuestOSException(
        f"We repeatedly failed to reboot the VM. Last exception caught: {check_reboot_exception}"
    )


def try_to_soft_restart(v_sphere, vmw_vm):
    """
    Issues the reboot task and catches the mysterious Invalid Fault.

    Tries up to max_reboot_attempts to get the reboot to go through.
      - If this limit is exceeded, the Invalid Fault is reraised for handling elsewhere.
      - If any other exception is encountered, we raise it immediately as it likely means that we cannot talk to the VM.

    :param VSphere v_sphere:
    :param vim.ManagedObject vmw_vm:
    :return:
    :raises vmodl.fault.SystemError: Usually an "Invalid Fault" which basically means "Computer Says No".
    :raises vim.fault.VimFault: VMware shit the bed.
    """

    wait_time = 30
    attempted_reboots = 0
    max_reboot_attempts = 5
    last_encountered_exception = None

    while attempted_reboots < max_reboot_attempts:
        try:
            v_sphere.logger.info("  **  Issuing Reboot command.")
            attempted_reboots += 1
            vmw_vm.RebootGuest()
            v_sphere.logger.info('  **  Successful reboot.')
            return

        except vmodl.fault.SystemError as last_encountered_exception:
            if 'invalid fault' not in last_encountered_exception.msg.lower():
                v_sphere.logger.error(f"  **  System error - Not due to Invalid Fault: {str(last_encountered_exception)}")
                raise last_encountered_exception

        attempted_reboots += 1
        v_sphere.logger.info(f"  **  Invalid Fault encountered - rebooting after {wait_time} seconds")
        time.sleep(wait_time)

    v_sphere.logger.error(f"  !!  VMWare Fault encountered: {str(last_encountered_exception)}")
    raise last_encountered_exception


def vmw_vm_check_soft_restarted_ok(v_sphere, vmw_vm):
    """
    Checks the state of a VM which has had the reboot command issued, to make sure that the reboot has happened and
    that VMWare Tools (and hence, the OS) is back up.

    Calls vmw_vm_wait_for_tools to wait for VMWare Tools to get back up
    to a responsive level. wait_for_tools may get a refreshed vmw_vm managed
    object, (due to pyvmomi sometimes losing its own SOAP object...) which is passed back here.

    :raises Exception: if the VM is not in the correct state, or something else went wrong when we tried to reboot.
    :raises vim.fault.VimFault: if there was a VMWare exception

    :param VSphere v_sphere:
    :param vim.ManagedObject vmw_vm:

    :returns vim.VirtualMachine: a refreshed managed object.
    """

    msg = "  **  Checking to see if the reboot is in progress."
    v_sphere.logger.info(msg)

    # Rebooting is a bit of a bugger. Sometimes it's so fast we miss it, sometimes it doesn't seem to get the
    # message to reboot (probably when the OS is busy doing something).
    # So for the too fast issue: We issue the command then look for VMWare Tools instead of the OS, because windows
    # can come back so quickly that we miss the reboot, but Tools always takes a few seconds.
    # For the second issue, we return False to the calling method to handle
    is_rebooting = False
    for x in range(0, 120):
        if vmw_vm.guest.toolsRunningStatus != "guestToolsRunning":
            msg = "  **  VM started rebooting!"
            v_sphere.logger.info(msg)
            is_rebooting = True
            break

        time.sleep(1)

    if not is_rebooting:
        msg = "  !!  VM refused to reboot!"
        v_sphere.logger.info(msg)
        raise VMWareBadState(msg)

    msg = "  **  VM soft restart request in progress. Waiting for tools to come back up"
    v_sphere.logger.info(msg)

    counter = 0
    while vmw_vm.guest.guestState != "running":
        msg = "  **  Waiting for VM to finish restarting"
        v_sphere.logger.info(msg)
        time.sleep(1)
        counter += 1
        if counter > 1800:
            msg = "  !!  Waited for VM to restart for 30 min with no change! :("
            v_sphere.logger.info(msg)
            raise VMWareGuestOSTimeoutException(msg)

    msg = "  **  VM restart finished!"
    v_sphere.logger.info(msg)

    wait_for_vmware_tools_response(v_sphere, vmw_vm)


def wait_for_vmware_tools_response(v_sphere, vmw_vm):
    """
    Function that pokes the given vmware vm until VMWare guest tools are running or 20 minutes pass.

    Tries to work around a bug in either pyvmomi or the vsphere API where *sometimes* the vmware tools status is not
    updated on change. To do this we take the service instance itself and after waiting 2 minutes for tools, we get
    a 'fresh' managed object of the VM and ask it what it's tools status is.

    USAGE: Use this after rebooting or powering on a VM when it's important that you know when VMWare tools is back.

    :raises Exception: when vmware tools did not come up.
    :param VSphere v_sphere:
    :param vim.VirtualMachine vmw_vm:
    :return: vim.VirtualMachine: the refreshed managed object
    :rtype bool:
    """

    v_sphere.logger.info("Waiting for VMWare Tools")
    wait_count = 0
    refreshes = 0
    while vmw_vm.guest.toolsRunningStatus != "guestToolsRunning":
        time.sleep(5)
        v_sphere.logger.info("Still waiting for tools, current status {}".format(vmw_vm.guest.toolsRunningStatus))
        wait_count += 1

        # If we waited 2 minutes, try to get a new Managed Object from the Service Instance
        if wait_count > 24:
            # If we've already done this 10 times, give up
            if refreshes >= 10:
                msg = "  !! Reboot program_command issued but VMWare Tools did not come up within 20 minutes! Help!"
                v_sphere.logger.error(msg)
                raise VMWareTimeout(msg)

            v_sphere.logger.info("Waited 2 minutes for tools. Refreshing VM Object from Service Instance. Might be bugged.")
            vmw_vm = v_sphere.get_vmw_obj_by_uuid(vmw_vm.config.uuid)
            refreshes += 1
