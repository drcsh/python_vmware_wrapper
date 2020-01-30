
class VMWareConnectionException(Exception):
    """
    Couldn't talk to VMWare. Probably a temporary failure.
    """
    pass

class VMWareInvalidInputException(Exception):
    """
    Bad input passed in from rest of the system
    """
    pass

class VMWareObjectNotFound(Exception):
    """
    When we looked for something and it wasn't in vSphere.
    """
    pass


class VMWareBadState(Exception):
    """
    Something VMWare side isn't in a state that we like the look of.
    """
    pass


class VMWareTimeout(Exception):
    """
    Something took too long to complete VMWare side.
    """
    pass


class VMWareGuestOSException(Exception):
    """
    Something went wrong when we were talking to the GuestOS
    """
    pass


class VMWareGuestOSTimeoutException(Exception):
    """
    The GuestOS didn't respond in a timely manner
    """
    pass


class VMWareGuestOSProcessUnknownException(Exception):
    """
    Something went wrong when we ran a process on the guest OS, but we can't tell what happened.
    """
    pass


class VMWareGuestOSProcessAmbiguousResultException(Exception):
    """
    A process run in the OS produced an ambiguous result - i.e. it produced no output, and this can be expected
    behaviour. Equally however, this could indicate a silent failure
    """
    pass


class VMWareGuestOSProcessBadOutputException(Exception):
    """
    A process run in the guest OS did not exit successfully and produced a result that we did not expect. This suggests
    an error occurred.
    """
    pass

class VMWareCreateDuplicateException(Exception):
    """
    We were asked to make something in vSphere which already exists
    """
    pass