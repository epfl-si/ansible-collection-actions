"""
When you are writing some Ansible code, and you want to compare things.
"""

from ansible.parsing.yaml.objects import AnsibleUnicode
from ansible_collections.epfl_si.actions.plugins.module_utils.strings import is_same_string

def is_substruct(a, b):
    """True iff `a` is recursively a sub-structure of `b`.

    Useful to compare Kubernetes objects, or more generally, whenever
    `a` is some YAML structure built from the configuration-as-code
    and `b` is the live system's current state.
    """
    if is_same_string(a, b):
        return True
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
