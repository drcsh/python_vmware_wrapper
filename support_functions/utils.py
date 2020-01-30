import unicodedata


def get_vmware_safe_string(input_str):
    """
    Given a string of characters which may contain accents or other unicode characters, first tries to replace accents
    e.g. "café" becomes "cafe"

    Then strips all non-ascii characters remaining.
    e.g.  "<Simplified Chinese Text>" becomes ""

    This is useful for writing say, customer names, to VMWAre when they could be accented or contain non-latin
    characters, because vSphere will happily accept those characters, then turn into a dribbling mess later when
    handling them...

    Based on https://stackoverflow.com/a/517974

    :param str input_str:
    :return: string safe to write to VMWare
    :rtype str:
    """
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    only_ascii = nfkd_form.encode('ASCII', 'ignore')
    return only_ascii.decode("utf-8")
