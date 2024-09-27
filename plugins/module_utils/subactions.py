from ansible.errors import AnsibleActionFail
from ansible_collections.epfl_si.actions.plugins.module_utils.ansible_api import AnsibleActions, AnsibleResults

class Subaction (object):
    """Models an Ansible action that your own action module invokes to perform its job.

    The following example supports `ansible-playbook --check` without further ado:

        from ansible_collections.epfl_si.actions.plugins.module_utils.ansible_api import AnsibleActions
        from ansible_collections.epfl_si.actions.plugins.module_utils.subactions import Subaction
        from ansible.plugins.action import ActionBase

        class MyAction (ActionBase):
            @AnsibleActions.run_method
            def run (self, ansible_api):
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

    Setting the `result` property to an Ansible result dict, will
    accumulate subaction results into said result dict everytime
    `query` or `change` is called. (In the code example above, we see
    that one can time the setting of `result` so as to discard query
    results; another possibility would be to use two separate
    instances of Subaction.)
    """

    def __init__ (self, ansible_api):
        self.result = None

        if isinstance(ansible_api, AnsibleActions):
            self.__ansible = ansible_api
        else:
            raise TypeError

    def query (self, action_name, args, failed_when=None):
        """Execute a read-only Ansible sub-action.

        If check mode is active (i.e. `ansible-playbook --check`), this action
        will still run.

        Only a cursory sanity check is performed on `action_name`;
        this method has is no way to tell if e.g. your `command` or
        `shell` invocation is indeed read-only (although it should be;
        otherwise consider using the `change` method instead).

        :param action_name: Ansible module name to use
        :param args: dict with arguments to give to module
        :param failed_when: An optional function that takes the result and returns
            a truthy value iff the action failed
        """
        def run_and_update_result (self, bypass_check_mode=None):
            query_result = self.__ansible.run_action(action_name, args, bypass_check_mode=bypass_check_mode)
            error = self._redress_failure(query_result, failed_when)
            if self.result is not None:
                AnsibleResults.update(self.result, AnsibleResults.unchanged(query_result))
            if error:
                raise error
            else:
                return query_result

        if (self.__ansible.check_mode.is_active and
            self._may_run_in_check_mode(action_name, args)):
            return run_and_update_result(self, bypass_check_mode=True)
        else:
            return run_and_update_result(self)

    def _may_run_in_check_mode (self, action_name, args):
        """True iff this action is safe to run in Ansible's check mode (i.e., it is read only)."""
        return action_name in ("command", "shell", "stat")

    def _is_check_mode_active (self):
        """Obsolete, please use ansible_api.AnsibleActions.check_mode.is_active instead."""
        return self.__ansible.check_mode.is_active

    def change (self, action_name, args, failed_when=None, update_result=None):
        """Execute an effectful Ansible sub-action.

        If check mode is active (i.e. ansible-playbook --check), nothing
        is done except simulating a change on the Ansible side (“orange”
        condition).

        :param action_name: Ansible module name to use
        :param args: Dict with arguments to give to module
        :param failed_when: An optional function that takes the result and returns
            a truthy value iff the action failed
        :param update_result: Obsolete, set the `result` object property instead

        :return: The Ansible result dict for the underlying action if update_result was None;
                 or the (changed) update_result parameter otherwise
        """
        if self.__ansible.check_mode.is_active:
            # Simulate "orange" condition, but don't actually do it
            result = dict(changed=True)
        else:
            result = self.__ansible.run_action(action_name, args)

        error = self._redress_failure(result, failed_when)

        if update_result is not None:
            AnsibleResults.update(update_result, result)
            if error:
                raise error
            else:
                return update_result   # Pretty debatable idea - Part of the reason why
                                       # update_result is obsolete
        else:
            if self.result is not None:
                AnsibleResults.update(self.result, result)
            if error:
                raise error
            else:
                return result

    def _redress_failure (self, result, failed_when):
        """Reset failure in `result` according to `failed_when`

        Returns an error that should be raised soon (after result
        bookkeeping) if unsuccessful i.e. `failed_when` returns True.

        :param result: An Ansible result dict. Will be mutated in place to
           delete the "failed" key (if present) if `failed_when`
           returns falsy
        :param failed_when: Either None, or a function that takes `result` as
           the sole parameter and returns a truthy value if there is a failure,
           or a falsy value if not.
        """
        if failed_when is None:
            failed_when = lambda result: 'failed' in result

        if failed_when(result):
            return AnsibleActionFail("Subaction failed: %s - Invoked with %s" % (
                result.get('msg', '(no message)'),
                result.get('invocation', '(no invocation information)')))

        # We will be returning None; scrub failure evidence out of result to
        # prevent clueless callers (such as the Ansible core) from freaking out
        if "rc" in result and str(result["rc"]) != "0":
            # This is a `command` or the like.
            result['failed'] = False  # Don't just delete it; lest task_executor.py:705 take it
                                      # upon itself to inspect ["rc"] again
            if 'msg' in result:
                # Not set by us, and typically misleading e.g. "non-zero return code"
                del result['msg']
        else:
            if 'failed' in result:
                del result['failed']

        return None
