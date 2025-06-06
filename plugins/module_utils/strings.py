"""
Both Ansible and Python have a hard time with strings for some reason.
"""

import inspect

from ansible.module_utils.six import text_type


def is_string_type (thing):
    if isinstance(thing, text_type):
        return True   # e.g. NativeJinjaText, AnsibleUnicode

    if hasattr(thing, "capitalize") and hasattr(thing, "encode"):
        return True   # e.g. AnsibleUnsafeText

    return False


def is_same_string (a, b):
    if not (is_string_type(a) and is_string_type(b)):
        return False

    # This is enough to see through all subclasses of str:
    a = str(a)
    b = str(b)

    # The annoying case is AnsibleUnsafeText:
    if hasattr(a, "_strip_unsafe"):
        a = a._strip_unsafe()
    if hasattr(b, "_strip_unsafe"):
        b = b._strip_unsafe()

    # I think we're done.
    return a == b
