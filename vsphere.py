import atexit
import ssl

from pyVim import connect
from pyVmomi import vim

from const import VM_POWER_STATE_ON, VM_POWER_STATE_OFF
from exceptions import VMWareObjectNotFound, VMWareBadState, VMWareConnectionException
from support_functions import power_functions, task_functions, search_functions, folder_functions
from support_functions.guest_os_interface import GuestOSInterface

import logging


class VSphere:
    """
        Wrapper class for talking to VMWare vSphere
    """
    DEFAULT_PORT = 443
    DEFAULT_LOGGER = logging.getLogger('info')

    @staticmethod
    def _validate_credentials(credentials):
        """
        Validates dict has all the correct properties to be used to connect to a vCenter
        :param credentials dict
        :return Boolean on success
        """
        for key in ['ip', 'user', 'data']:
            if key not in credentials:
                return False

        return True

    def __init__(self, uri, username, password, port=DEFAULT_PORT, logger=DEFAULT_LOGGER):
        """

        :param str uri: URL/IP of vSphere to talk to
        :param str username:
        :param str password: plain text password.
        :param int port: (optional)
        :param logger logger: 
        """
        # Main class vars
        self.uri = uri
        self.port = port
        self._username = username
        self._password = password
        self.logger = logger

        # These are set up here and will be optionally populated on use
        self._process_manager = None
        self._file_manager = None
        self.vmw_objs = {}

        # Try to Connect
        self._service_instance = self._connect()

    def _connect(self):
        """
        Connect to vSphere and get a Service Instance which is how we interact with the API (via Pyvmomi)

        :return: service_instance
        :rtype vim.ServiceInstance:
        """

        context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        context.verify_mode = ssl.CERT_NONE

        self.logger.info(f" VSphere: Connecting to vSphere at {self.uri}")

        try:
            service_instance = connect.SmartConnect(host=self.uri,
                                                    user=self._username,
                                                    pwd=self._password,
                                                    port=self.port,
                                                    sslContext=context)
        except Exception as error:
            raise VMWareConnectionException(f'Could not connect to vCentre: {self.uri} reason given {error}')

        atexit.register(self.logger.info, f" VSphere: Disconnecting from vSphere")
        atexit.register(connect.Disconnect, service_instance)

        return service_instance

    def get_service_instance(self, force_refresh=False):
        """
        Fetch the vmware service instance for interacting with the SOAP API. If there isn't one, gets one.

        Sometimes the service instance falls over and needs to be restarted, if/when this happens, set force_refresh
        to True.

        :param bool force_refresh: (Optional) set to True to always get a new Service Instance
        :return: self._service_instance
        :rtype vim.ServiceInstance:
        """
        if not self._service_instance or force_refresh:
            self._service_instance = self._connect()

        return self._service_instance

    def get_process_manager(self, force_refresh=False):
        """
        Returns the VMWare processManager, used for running processes inside guest OSs.

        :param bool force_refresh: (optional) if set to True, will get a new processManager and service instance.
        :return:
        """

        if not self._process_manager or force_refresh:
            service_instance = self.get_service_instance(force_refresh)
            self._process_manager = service_instance.vmw_content.guestOperationsManager.processManager

        return self._process_manager

    def get_file_manager(self, force_refresh=False):
        """
        Returns the VMWare fileManager, used for performing file operations on a VM, such as fetching files from the
        guest OS.

        :param force_refresh:
        :return:
        """
        if not self._file_manager or force_refresh:
            service_instance = self.get_service_instance(force_refresh)
            self._file_manager = service_instance.vmw_content.guestOperationsManager.fileManager

        return self._file_manager

    def load_vmw_obj_by_name(self, vimtype, name):
        """
        Searches vCenter for an object of the given type and name and loads it into self.vmw_objs

        Note that this is not a fast operation and should be avoided if possible.

        :param class vimtype:
        :param str name:
        :return:
        :rtype vim.ManagedObject: Return a vmware object of the given vimtype
        :raises VMWareObjectNotFound: No object of that name + type in VMWare.
        """
        vmw_data = search_functions.get_vmw_objects_of_type(self.get_service_instance(), vimtype)

        for result in vmw_data:
            if result["name"] == name:
                vmw_obj = result["obj"]
                self.vmw_objs[name] = vmw_obj
                return vmw_obj

        raise VMWareObjectNotFound(f"Could not find {vimtype} with name {name}!")

    def get_vmw_obj_by_name(self, vimtype, name):
        """
        Get the vsphere object associated with a given text name. If we already have a copy in self.vmw_objects,
        we return that. Otherwise we go looking for it.

        :note: Pretty sure the container view search logic here came from the community samples, but I can't find the
        original source.

        :param vim.ServiceInstance v_sphere: VMWare Service Instance
        :param class vimtype: vim.XXXX vim class of the object to retreive. E.g. vim.VirtualMachine
        :param str name: Plain text name we're looking for.
        :return object:
        :rtype vim.ManagedObject: Managed object, specifically of vimtype
        :raises VMWareObjectNotFound: No object of that name + type in VMWare.
        """

        vmw_obj = self.vmw_objs.get(name)
        if vmw_obj:
            if type(vmw_obj) == vimtype:
                return vmw_obj
            else:
                raise TypeError(f"Requested vmw object of type {vimtype}, got {vmw_obj}")

        else:
            return self.load_vmw_obj_by_name(vimtype, name)

    def get_vmw_obj_by_uuid(self, uuid):
        """
        Find a VMWare object by UUID. The object will be added to the vmw_objs
        list (indexed by its name).

        :param str uuid:
        :return:
        :rtype vim.ManagedObject:
        :raises VMWareObjectNotFound: No resource with that UUID.
        """
        search_index = self.get_service_instance().content.searchIndex
        vmw_obj = search_index.FindByUuid(None, uuid, True, False)

        if vmw_obj:
            self.vmw_objs[vmw_obj.name] = vmw_obj
            return vmw_obj

        raise VMWareObjectNotFound(f"No result for {uuid}")

    def get_vm_folder(self, folder_name):
        return self.get_vmw_obj_by_name(vim.Folder, folder_name)

    def get_vm(self, vm_name):
        return self.get_vmw_obj_by_name(vim.VirtualMachine, vm_name)

    def get_guestosinterface_for_vm(self, vm_name, os_username, os_password):
        """
        Get a GuestOSInterface (for communicating with the guest OS) for a virtual machine. 
        
        :param str vm_name: Name of the VM
        :param str os_username: username to log in to the guest OS
        :param str os_password: password for the guest OS user
        :return:
        :rtype: GuestOSInterface
        """
        return GuestOSInterface(self, vm_name, os_username, os_password)

    def clone_machine(self,
                      template_name,
                      target_host_name,
                      target_datastore_name,
                      target_folder_name,
                      new_vm_name):
        """
        Given a vim.VM to clone, the name of the host and the datastore on that
        host, as well as the VM Folder to put it into and the name to assign it, this function asks vSphere for
        these objects and builds a clonespec which is then run to create the VM.

        :param str template_name:
        :param str target_host_name:
        :param str target_datastore_name:
        :param str target_folder_name:
        :param str new_vm_name:
        :return: None
        :raises VMWareBadState: if there is a problem with things in VMWare which prevents us proceeding
        :raises VMWareObjectNotFound: if we can't find required objects in VMWare.
        """

        self.logger.info(f" VSphere: Getting ready to clone VM {template_name}")

        vmw_vm_template = self.get_vmw_obj_by_name(vim.VirtualMachine, template_name)

        self.logger.info(f" VSphere: Looking for VM Host {target_host_name}")
        vmw_host = self.get_vmw_obj_by_name(vim.HostSystem, target_host_name)

        if vmw_host.summary.runtime.inMaintenanceMode:
            raise VMWareBadState("Target host is in Maintanence Mode! Can't deploy there!")

        self.logger.info(f" VSphere: Looking for VMware Datastore {target_datastore_name}")
        vmw_datastore = self.get_vmw_obj_by_name(vim.Datastore, target_datastore_name)

        self.logger.info(f" VSphere: Looking for VM Folder {target_folder_name}")
        vmw_folder = self.get_vmw_obj_by_name(vim.Folder, target_folder_name)

        self.logger.info(" VSphere: Building clone specification")
        # Relocation spec - where the VM will be stored and hosted
        relospec = vim.vm.RelocateSpec()
        relospec.datastore = vmw_datastore
        relospec.host = vmw_host
        relospec.pool = vmw_host.parent.resourcePool

        # Put the hardware and location config together in the clone specification
        clonespec = vim.vm.CloneSpec()
        clonespec.location = relospec
        clonespec.powerOn = False
        clonespec.template = False

        self.logger.info(f" VSphere: Cloning {new_vm_name} to {vmw_folder} on {vmw_host}. This will take some time...")
        try:
            task = vmw_vm_template.Clone(folder=vmw_folder, name=new_vm_name, spec=clonespec)
        except vim.fault.NoPermission as e:
            raise VMWareBadState(f"Permissions Error: Not allowed to clone VM template! Err: {str(e)}")

        result = task_functions.wait_for_task_complete(self, task)
        if not result:
            raise VMWareBadState(f"VMWare failed to clone the VM! Check the vSphere logs.")

        self.logger.info(f" VSphere: Congratulations! It's a Virtual Machine!")

    def configure_machine(self, vm_name, vm_network_name, hardware_specs):
        """
        Reconfigures a VM (given by VM Name) to have the hardware specs provided and be connected to the VMNetwork
        specified.

        TODO: Split into separate methods

        :param str vm_name:
        :param str vm_network_name:
        :param dict hardware_specs: {'vcpus': int, 'memory': int, 'hdd': int}
        :return:
        """

        requested_vcpus = int(hardware_specs['vcpus'])
        requested_memory = int(hardware_specs['memory'])
        requested_hdd = int(hardware_specs['hdd'])

        vmw_vm = self.get_vmw_obj_by_name(vim.VirtualMachine, vm_name)

        self.logger.info(f" VSphere: Looking for VMware Network {vm_network_name}")
        vmw_network = self.get_vmw_obj_by_name(vim.Network, vm_network_name)

        devices = []

        # VM Network Settings
        nic = vim.vm.device.VirtualDeviceSpec()
        nic.operation = vim.vm.device.VirtualDeviceSpec.Operation.edit
        nic.device = vim.vm.device.VirtualVmxnet3()
        nic.device.wakeOnLanEnabled = True
        nic.device.addressType = 'assigned'
        nic.device.key = 4000
        nic.device.deviceInfo = vim.Description()
        nic.device.deviceInfo.label = "Network Adapter"
        nic.device.deviceInfo.summary = vmw_network.name
        nic.device.backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo()
        nic.device.backing.network = vmw_network
        nic.device.backing.deviceName = vmw_network.name
        nic.device.backing.useAutoDetect = False
        nic.device.connectable = vim.vm.device.VirtualDevice.ConnectInfo()
        nic.device.connectable.startConnected = True
        nic.device.connectable.allowGuestControl = True
        devices.append(nic)

        # Dealing with template disk size
        try:
            template_disk = [x for x in vmw_vm.config.hardware.device
                             if isinstance(x, vim.vm.device.VirtualDisk)][0]
        except IndexError:
            raise VMWareBadState("Somehow this VM {vm} has no discs. Cannot resize!")

        template_disk_size_kb = int(
            template_disk.deviceInfo.summary.split(" ")[0].replace(",", "").replace(".", ""))

        # Annoyingly VMWare works in Kb
        requested_hdd_kb = requested_hdd * 1024 * 1024

        if requested_hdd_kb > template_disk_size_kb:
            # Need to resize the disk
            self.logger.info(f" VSphere: increasing disk size to {requested_hdd_kb} KB as it's bigger than the template "
                  f"size ({template_disk_size_kb} KB)")

            virtual_disk_spec = vim.vm.device.VirtualDeviceSpec()
            virtual_disk_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.edit
            virtual_disk_spec.device = template_disk
            virtual_disk_spec.device.capacityInBytes = requested_hdd_kb * 1024
            devices.append(virtual_disk_spec)
            new_disk_size_kb = requested_hdd_kb
        else:
            new_disk_size_kb = template_disk_size_kb
            self.logger.info(f" VSphere: requested disc size is equal to or smaller than the template. Not resizing disc")


        # Set VM Hardware config spec
        new_spec = vim.vm.ConfigSpec()
        new_spec.numCPUs = requested_vcpus
        new_spec.memoryMB = requested_memory
        new_spec.cpuHotAddEnabled = True
        new_spec.memoryHotAddEnabled = True
        new_spec.deviceChange = devices

        # Do the HW reconfiguration
        self.logger.info(f" VSphere: Reconfiguring hardware: Num CPUs: '{requested_vcpus}' Mem (MB): '{requested_memory}'")

        task = vmw_vm.ReconfigVM_Task(spec=new_spec)

        success = task_functions.wait_for_task_complete(self, task, timeout_seconds=60)

        if not success:
            raise VMWareBadState("VMWare failed to reconfigure the VM! Check the vSphere logs.")

        self.logger.info(f" VSphere: VM {vm_name} should now have the correct hardware specs")

    def get_vm_power_state(self, vm_name):
        """
        Fetch the power state of the VM as reported by VMWare, this will be a string like "PoweredOn".

        :param vm_name:
        :return:
        :rtype string:
        """
        vmw_vm = self.get_vm(vm_name)
        return vmw_vm.summary.runtime.powerState

    def get_vm_is_powered_on(self, vm_name):
        """
        :param vm_name:
        :return: True if the VM is powered on, otherwise False.
        :rtype bool:
        """
        return self.get_vm_power_state(vm_name) == VM_POWER_STATE_ON

    def get_vm_is_powered_off(self, vm_name):
        """
        You may be wondering why this isn't just !powered_on. Well, the fact is, we don't trust VMWare to not have
        additional states, like restarting, standby, etc.
        :param vm_name:
        :return: True if the VM is powered off, otherwise False.
        :rtype bool:
        """
        return self.get_vm_power_state(vm_name) == VM_POWER_STATE_OFF

    def power_on_vm_and_wait_for_os(self, vm_name):
        """
        Given a VM name, finds the VM and switches it on. Returns when the OS is responding.

        :param str vm_name:
        :raises VMWareTimeout: Took too long to complete
        :return:
        """
        vmw_vm = self.get_vm(vm_name)
        power_functions.power_on_vm_and_wait_for_os(self, vmw_vm)

    def power_off_vm_soft(self, vm_name):
        """
        Ask the OS on the given VM to shut down, please.

        :param str vm_name:
        :raises VMWareTimeout: Took too long to complete
        :return:
        """
        vmw_vm = self.get_vm(vm_name)
        power_functions.power_off_vm_soft(self, vmw_vm)

    def power_off_vm_hard(self, vm_name):
        """
        Switch off the VM from the host. This is like pulling the plug.

        :param str vm_name:
        :raises VMWareTimeout: Took too long to complete
        :return:
        """
        vmw_vm = self.get_vm(vm_name)
        power_functions.power_off_vm_hard(self, vmw_vm)

    def restart_vm_soft(self, vm_name):
        """
        Talk to the OS and ask it to restart. Wait until the OS is back up and responding before returning.

        :raises VMWareBadState: One of the many weird things that can break in VMWare, broke.
        :raises VMWareGuestOSTimeoutException: OS didn't come back in a timely manner.
        :raises VMWareGuestOSException: We tried several times to tell it to restart, but it didn't listen.
        :raises VMWareTimeout: Took too long to complete
        :param str vm_name:
        :return:
        """
        vmw_vm = self.get_vm(vm_name)
        power_functions.restart_vm_soft_and_wait_for_tools(self, vmw_vm)

    def restart_vm_hard(self, vm_name):
        """
        Restart the VM from the host level. Less likely to go wrong than soft restarting.

        :param str vm_name:
        :raises VMWareTimeout: Took too long to complete
        :return:
        """
        vmw_vm = self.get_vm(vm_name)
        power_functions.restart_vm_hard(self, vmw_vm)

    def destroy_vm(self, vm_name):
        """
        Destroys the given VM. If it's not switched off, it will be hard shut down before
        destruction.

        :param str vm_name:
        :raises VMWareTimeout: Took too long to complete
        :return:
        """
        if not self.get_vm_is_powered_off(vm_name):
            self.power_off_vm_hard(vm_name)

        vmw_vm = self.get_vm(vm_name)
        task = vmw_vm.Destroy_Task()
        task_functions.wait_for_task_complete(self, task, 10)


    def update_vm_custom_fields(self, vm_name, field_name, field_value):
        """
        Updates customfields on a vmware vm object. if the field is named 'Notes',
        it goes instead into the vm's Annotations. specifying field_value='' will
        clear the field/annotations.

        :param str vm_name:
        :param str field_name:
        :param str field_value:
        :raises VMWareTimeout: Took too long to complete
        :return:
        """

        vmw_vm = self.get_vm(vm_name)

        if field_name == "Notes":
            annotation = vmw_vm.config.annotation

            spec = vim.vm.ConfigSpec()
            spec.annotation = field_value

            task = vmw_vm.ReconfigVM_Task(spec)

            task_functions.wait_for_task_complete(self, task, 20)

        else:
            try:
                # for all other (non-Notes) customfields, we instead dump the values
                # into vcenter's customfields
                available_vm_fields = vmw_vm.availableField
                target = False

                # find or make fields object with fuzzy match for email and account
                if "email" in field_name.lower():
                    for vm_field in available_vm_fields:
                        if "email" in vm_field.name.lower():
                            target = vm_field
                            break
                elif "account" in field_name.lower():
                    for vm_field in available_vm_fields:
                        if "account" in vm_field.name.lower():
                            target = vm_field
                            break
                else:
                    for vm_field in available_vm_fields:
                        if field_name.lower() == vm_field.name.lower():
                            target = vm_field
                            break

                # if we couldn't find the target field, then create it - iff we want
                # to put a value into it
                if not target:
                    target = self._service_instance.content.customFieldsManager.AddFieldDefinition(
                        name=field_name,
                        moType=vim.VirtualMachine
                    )

                self._service_instance.content.customFieldsManager.SetField(
                    entity=vmw_vm,
                    key=target.key,
                    value=field_value
                )
            except Exception as e:
                raise VMWareBadState(f"Couldn't add or update custom field due to error: {str(e)}")

    def create_folder(self, parent_folder_name, new_folder_name):
        """
        Create a new VM Folder, requires the name of the folder you want to put it in (parent folder).
        :param str parent_folder_name:
        :param str new_folder_name:
        :return:
        """
        parent_folder = self.get_vm_folder(parent_folder_name)
        folder_functions.create_folder(self, parent_folder, new_folder_name)

    def move_vm_to_folder(self, vm_name, target_folder_name):
        """
        :param str vm_name:
        :param str target_folder_name:
        :param VSphere vsphere: Added by the decorator
        :raises VMWareTimeout: Took too long to complete
        :raises VMWareBadState:  Task didn't exit successfully
        :return:
        """
        vmw_folder = self.get_vm_folder(target_folder_name)
        vmw_machine = self.get_vm(vm_name)
        result = folder_functions.move_vm_to_folder(self, vmw_machine, vmw_folder)

        if not result:
            raise VMWareBadState("VMWare Task to move VM Failed")
