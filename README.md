# `epfl_si.actions`

The [epfl_si.actions collection on Ansible
Galaxy](https://galaxy.ansible.com/epfl_si/actions) makes it easier to
write Ansible action modules.

## `Subaction` Class

This class encapsulates the calling of other Ansible actions from within your action module. It also knows the difference between a *query* (which never causes orange, and should run under `ansible-playbook --check`) and a *change* (which can, and shouldn't).

The following example supports `ansible-playbook --check` without further ado:

```python
from ansible.plugins.action import ActionBase
from ansible_collections.epfl_si.actions.plugins.module_utils.subactions import Subaction

class MyAction (ActionBase):
    @AnsibleActions.run_method
    def run (self, args, ansible_api):
        a = Subaction(ansible_api)
        probe_result = a.query("command",
                               dict(_raw_params="ls",
                                    chdir="/etc/apache2"))

        # Ponder probe_result...
        a.result = {}
        a.change("command",
                 dict(_raw_params="touch zoinx.conf",
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

## `ansible_api` Module

The
`ansible_collections.epfl_si.actions.plugins.module_utils.ansible_api`
module contains classes `AnsibleActions` and `AnsibleResults` and
`AnsibleCheckMode` that will strive to keep a stable API, no matter
what happens to the Ansible internals further down the road.

- An `AnsibleActions` instance can be constructed using the `@AnsibleActions.run_method` decorator, as shown above. Such an instance encapsulates the `run_action` method, which lets one invoke an Ansible action directly (although note that if you want out-of-the-box `--check` support, consider going through a `Subaction` instance instead which has that as a feature)
- An `AnsibleCheckMode` instance can be obtained from the `.check_mode` property of an `AnsibleActions` instance. It offers the `is_active` property to inspect Ansible's check mode.
- The `AnsibleResults` “pure-static” class takes care of meddling with Ansible result dicts on your behalf.

## `Postcondition` Class

The above example could be written in even simpler a style, if you are
willing to throw some OO into the mix:

```python

from ansible.plugins.action import ActionBase
from ansible_collections.epfl_si.actions.plugins.module_utils.subactions import Subaction
from ansible_collections.epfl_si.actions.plugins.module_utils.ansible_api import AnsibleResults
from ansible_collections.epfl_si.actions.plugins.module_utils.postconditions import run_postcondition, Postcondition

class MyAction (ActionBase):
    @AnsibleActions.run_method
    def run (self, args, ansible_api):
        result = {}
        subaction = Subaction(ansible_api)
        subaction.result = result
        AnsibleResults.update(result,
                              run_postcondition(new ApacheConfigIsJustAsIWantIt(subaction)))
        return result

class ApacheConfigIsJustAsIWantIt (Postcondition):
    def __init__(self, subaction):
        self.subaction = subaction

    def holds (self):
        probe_result = self.subaction.query("command", dict(_raw_params="ls", chdir="/etc/apache2"))
        if (looks_all_good(probe_result)):
            return True
        else:
            return False

    def enforce (self):
        self.subaction.change("command",
                    dict(_raw_params="touch zoinx.conf", chdir="/etc/apache2"))
        
```

The `Postcondition` abstract base class

- helps you separate concerns between *checking* the postcondition (in an overloaded `holds` method) and *enforcing* it (`enforce` method)
- comes with an “executor” function, `run_postcondition` that takes care of calling the methods in the correct order, and computing the Ansible result thereof
- when combined with `Subaction` as shown, lets you focus on writing your action and pretty much forget about the management of your action's own Ansible result dict
