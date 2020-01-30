from pyVmomi import vim, vmodl


def get_vmw_objects_of_type(service_instance, vimtype):
    """
    Returns a list of dicts with information gathered from vSphere, and the SOAP object for each result.

    :param class vimtype:
    :return:
    :rtype [dict]: Each item in the list is a dict representing an object in vmware. The 'obj' key is the SOAP object.
    """

    view = get_container_view(service_instance=service_instance, obj_type=[vimtype])
    vmw_data = collect_properties(service_instance=service_instance, view_ref=view, obj_type=vimtype, include_mors=True)
    view.DestroyView()  # TODO: maybe breaking
    return vmw_data


def get_container_view(service_instance, obj_type, container=None):
    """
    Get a vSphere Container View reference to all objects of type 'obj_type'

    It is up to the caller to take care of destroying the View when no longer needed.

    Original Source: https://github.com/dnaeon/py-vconnector/blob/master/src/vconnector/core.py
    Modified for my purposes here.

    :param list obj_type: A list of managed object types
    :return: A container view ref to the discovered managed objects
    :rtype: ContainerView
    """

    if not container:
        container = service_instance.content.rootFolder

    view_ref = service_instance.content.viewManager.CreateContainerView(
        container=container,
        type=obj_type,
        recursive=True
    )
    return view_ref


def collect_properties(service_instance, view_ref, obj_type, path_set=None, include_mors=False):
    """
    Collect properties for managed objects from a view ref

    Check the vSphere API documentation for example on retrieving
    object properties:

        - http://goo.gl/erbFDz


    Original Source: https://github.com/dnaeon/py-vconnector/blob/master/src/vconnector/core.py
    Modified for my purposes here.

    :param pyVmomi.vim.view.* view_ref: Starting point of inventory navigation
    :param pyVmomi.vim.* obj_type: Type of managed object
    :param list path_set: List of properties to retrieve
    :param bool include_mors: If True include the managed objects refs in the result

    :return: A list of properties for the managed objects
    :rtype list:
    """

    collector = service_instance.content.propertyCollector

    # Create object specification to define the starting point of
    # inventory navigation
    obj_spec = vmodl.query.PropertyCollector.ObjectSpec()
    obj_spec.obj = view_ref
    obj_spec.skip = True

    # Create a traversal specification to identify the path for collection
    traversal_spec = vmodl.query.PropertyCollector.TraversalSpec()
    traversal_spec.name = 'traverseEntities'
    traversal_spec.path = 'view'
    traversal_spec.skip = False
    traversal_spec.type = view_ref.__class__
    obj_spec.selectSet = [traversal_spec]

    # Identify the properties to the retrieved
    property_spec = vmodl.query.PropertyCollector.PropertySpec()
    property_spec.type = obj_type

    if not path_set:
        property_spec.all = True

    property_spec.pathSet = path_set

    # Add the object and property specification to the
    # property filter specification
    filter_spec = vmodl.query.PropertyCollector.FilterSpec()
    filter_spec.objectSet = [obj_spec]
    filter_spec.propSet = [property_spec]

    # Retrieve properties
    props = collector.RetrieveContents([filter_spec])

    data = []
    for obj in props:
        properties = {}
        for prop in obj.propSet:
            properties[prop.name] = prop.val

        if include_mors:
            properties['obj'] = obj.obj

        data.append(properties)
    return data
