import time

import requests
from pyVmomi import vim

from exceptions import VMWareGuestOSException, VMWareGuestOSTimeoutException, \
    VMWareGuestOSProcessUnknownException, VMWareBadState, VMWareGuestOSProcessAmbiguousResultException, \
    VMWareGuestOSProcessBadOutputException


class GuestOSCommand:

    def __init__(self,
                 program_path,
                 program_command,
                 description='',
                 output_file_location='',
                 success_outputs=list,
                 timeout_seconds=120):
        """
        Data class for holding information about a command to be run on the Guest OS by the GuestOSInterface.

        :param str program_path: The path of the program to run. e.g. C:\Windows\System32\cmd.exe
        :param str program_command: The command to pass to that program
        :param str description: (optional) a plain text description of what this does. Used for logging.
        :param str output_file_location: (optional) where to put any output of this command. Used to check for success
        :param list(str) success_outputs: (optional) output expected in the output file if successful
        :param int timeout_seconds: How long to wait if no input returned before deciding that the command failed
        """
        self.program_path = program_path
        self.program_command = program_command
        self.description = description
        self.output_file_location = output_file_location
        self.success_outputs = success_outputs
        self.timeout_seconds = timeout_seconds

    def __str__(self):
        if self.description:
            return f"GuestOSCommand: {self.description}"
        return f"GuestOSCommand: {self.program_path} {self.program_command}"


class GuestOSInterface:
    """
        Interface for talking to the guest OS. Masks the complicated inner workings of VMWare.
    """

    def __init__(self, vsphere, vmname, username, password):
        self.vsphere = vsphere
        self.vmname = vmname
        self.vm_obj = vsphere.get_vmw_obj_by_name(vim.VirtualMachine, vmname)
        self.process_manager = vsphere.get_process_manager()
        self.file_manager = vsphere.get_file_manager()
        self.login_credentials = vim.vm.guest.NamePasswordAuthentication(
            username=username, password=password
        )

    def run_command_and_check_result(self, command):
        """
        Rus a GuestOSCommand on self.vm_obj. If the exit code reports a success, all is well. Otherwise, tries to
        determine what happened by checking the output (if it was stored) and looking for expected success messages
        as defined in the GuestOSCommand.

        :param GuestOSCommand command:
        :return:
        """

        pid = self.run_command(command.program_path, command.program_command, command.output_file_location)

        command_running = True
        check_output = False

        if pid == 0:
            raise VMWareGuestOSException(f"No Process ID returned running {command}")

        '''
            Make sure that the program_command has finished before we move on to the next one
        '''
        timeout_counter = 0
        while command_running:

            # Default to breaking the loop as there are several exit conditions and only 1 continue.
            command_running = False

            process_list = self.process_manager.ListProcessesInGuest(self.vm_obj,
                                                                     self.login_credentials,
                                                                     [pid])

            # It is possible that we don't get any info back, in this case, we give up looking and check output
            if len(process_list) == 0:
                raise VMWareGuestOSException(
                    f"No process info returned by the GuestOS. Can't check status of {command}"
                )

            process_info = process_list.pop()

            # Here we look for an exit code. If there isn't one, the process is running
            if process_info.exitCode is not None:

                # 0 is the "all good" response.
                if process_info.exitCode == 0:
                    return

            elif timeout_counter > command.timeout_seconds:
                raise VMWareGuestOSTimeoutException(f"{command} did not finish in < {command.timeout_seconds}s")

            # If there's no exit code, and we didn't time out, keep waiting.
            timeout_counter += 5
            time.sleep(5)

        '''
            If we didn't return earlier, something went wrong. We now try to check the output of the process, this
            relies on the output being redirected to file.
        '''
        # If we've flagged the program_command for a check but we have no output redirect, we'll need to note this...
        if not command.output_file_location:
            raise VMWareGuestOSProcessUnknownException(
                f"{command} did not complete successfully but no output file was specified, so the output was not " 
                "recorded."
            )

        # Unfortunately the way vSphere gives us access to files is to host them on a webserver on the vm host (!!!)
        # We therefore have to get-request it. I assume there are various reasons that the file won't be there etc, but
        # the documentation is not clear...
        vmw_file_transfer_obj = self.file_manager.InitiateFileTransferFromGuest(
            self.vm_obj,
            self.login_credentials,
            command.output_file_location
        )

        url = vmw_file_transfer_obj.url

        if not url:
            # I assume this is possible...
            raise FileNotFoundError(f"Couldn't locate file {command.output_file_location} when running {command} - "
                                    f"VMWare didn't return a URL")

        resp = requests.get(url, verify=False)

        if not resp.status_code == 200:
            raise VMWareBadState(f"Didn't receive an appropriate response from VMWare when attempting to retrieve "
                                 f"the output file {command.output_file_location} for {command}. "
                                 f"Expected an HTTP 200 response, but received a {resp.status_code}: {resp.reason}")

        # The cmd output adds new lines etc. So we strip them out to avoid issues.
        file_contents = resp.text.replace("\r", "").replace("\n", "").strip(" ")

        # If we got the file, check it's an expected output. If it isn't, append an error.
        # This is complicated by blank results (sometimes expected) and complex results which we want to
        # look for the success message contained in.

        # Check for expected blank output
        if file_contents.strip() == '' and '' in command.success_outputs:
            raise VMWareGuestOSProcessAmbiguousResultException(
                f"{command} did not exit successfully, but a blank output was found, and a blank output "
                "can be expected. This could mean that the program_command failed silently."
            )

        # Deal with text output
        for expected_result in command.success_outputs:
            if expected_result in file_contents:
                return  # success

        raise VMWareGuestOSProcessBadOutputException(
            f"{command} did not exit successfully, and an unexpected result was recorded in the output file: "
            f"{file_contents}"
        )

    def run_command(self, path, command, output_file_location=''):
        """
        Execute a program_command in the shell/program_command line of the target OS.

        :param str path: The location of the program to execute. E.g. the program_path to bash or cmd.exe/powershell
        :param str command: The program_command to run
        :param str output_file_location: (optional) if you want the output to be captured for checking, set a program_path.
        :return: the Process ID of the process in the guest OS
        :rtype int:
        """

        if output_file_location:
            command = f"{command} > {output_file_location}"

        print(f"Running {path} {command}")

        program_spec = vim.vm.guest.ProcessManager.ProgramSpec(
            programPath=path,
            arguments=command
        )

        try:
            pid = self.process_manager.StartProgramInGuest(self.vm_obj, self.login_credentials, program_spec)
        except Exception as e:
            raise VMWareGuestOSException(f"Could not run program_command in guest: '{command}' Exception: {str(e)}")

        print(f"Command sent to {self.vmname} and returned PID {pid}")

        return pid
