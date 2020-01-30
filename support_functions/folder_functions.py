from pyVmomi import vim

from exceptions import VMWareInvalidInputException, VMWareCreateDuplicateException
from support_functions.task_functions import wait_for_task_complete


def move_vm_to_folder(v_sphere, v_machine, vm_folder):
    """
    Attempts to move VM to a folder within the one vCenter
    :v_machine VM instance
    :vm_folder vm_folder instance
    :return boolean on success
    """
    task = vm_folder.MoveInto([v_machine])

    return wait_for_task_complete(v_sphere, task, timeout_seconds=60)


def create_folder(v_sphere, vmw_parent_folder, new_folder_name):
    """
    Creates a new sub VM folder attached to a parent folder
    :param vim.VMFolder vmw_parent_folder: folder to put the new folder in
    :param str new_folder_name:
    :return:
    """
    try:
        vmw_parent_folder.CreateFolder(new_folder_name)
        return

    except vim.fault.DuplicateName:
        raise VMWareCreateDuplicateException(f'Folder name {new_folder_name} already in use')

    except vim.fault.InvalidName:
        raise VMWareInvalidInputException(f'Folder name {new_folder_name} is invalid')
