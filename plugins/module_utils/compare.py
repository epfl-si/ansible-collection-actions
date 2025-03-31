"""
When you are writing some Ansible code, and you want to compare things.
"""

from ansible.parsing.yaml.objects import AnsibleUnicode
from ansible.utils.unsafe_proxy import AnsibleUnsafeText


def is_substruct(a, b):
    """True iff `a` is recursively a sub-structure of `b`.

    Useful to compare Kubernetes objects, or more generally, whenever
    `a` is some YAML structure built from the configuration-as-code
    and `b` is the live system's current state.
    """
    if type(a) == AnsibleUnicode:
        return is_substruct(str(a), b)
    elif type(b) == AnsibleUnicode:
        return is_substruct(a, str(b))
    if type(a) == AnsibleUnsafeText:
        return is_substruct(a._strip_unsafe(), b)
    elif type(b) == AnsibleUnsafeText:
        return is_substruct(a, b._strip_unsafe())
    elif type(a) != type(b):
        return False
    elif type(a) == dict:
        for k in a.keys():
            if k not in b:
                return False
            if not is_substruct(a[k], b[k]):
                return False
        return True
    elif type(a) == list:
        if len(a) != len(b):
            return False
        for (a_elem, b_elem) in zip(a, b):
            if not is_substruct(a_elem, b_elem):
                return False
        return True
    else:
        return a == b
