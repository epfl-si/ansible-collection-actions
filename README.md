# `epfl_si.actions`

The [epfl_si.actions collection on Ansible
Galaxy](https://galaxy.ansible.com/epfl_si/actions) makes it easier to
write Ansible action modules.

## `Subaction` Class

This class encapsulates the calling of other Ansible actions from within your action module.

The following example supports `ansible-playbook --check` without further ado:

```python
from ansible.plugins.action import ActionBase
from ansible_collections.epfl_si.actions.plugins.module_utils.subactions import Subaction
from ansible_collections.epfl_si.actions.plugins.module_utils.ansible_api import AnsibleActions

class MyAction(ActionBase):
    @AnsibleActions.run_method
    def run(self, args, ansible_api):
        self.result = {}
        a = SubAction(ansible_api)
        probe_result = a.query("command",
                               dict(_raw_params="ls",
                                    chdir="/etc/apache2"))

        # Ponder probe_result...
        a.result = {}
        a.change("command",
                 dict(_raw_params="touch",
                      chdir="/etc/apache2")))
        return a.result
```

This class
- Abstracts away the complexities of the underlying Ansible API (which differs depending on whether you want to invoke “standard” and “home-grown” action modules)
- Forces callers to explicitly distinguish between **changes** and **queries**
- Ensures that queries also run under `ansible-playbook --check`
- Ensures that changes *do not* run under `ansible-playbook --check` (but simulate “orange” in that case instead)
- Provides (but does not impose) a way to accumulate Ansible-style result dicts across multiple changes, without masking prior failures
- Raises `ansible.errors.AnsibleActionFail` upon failure in a query or a change (but still updates result dicts correctly
when a change fails, so that callers can safely catch that exception and continue)
