from ansible.errors import AnsibleActionFail
from ansible_collections.epfl_si.actions.plugins.module_utils.ansible_api import AnsibleActions, AnsibleResults

class Subaction(object):
    """Models an Ansible action that your own action module invokes to perform its job.

    The following example supports `ansible-playbook --check` without further ado:

        from ansible_collections.epfl_si.actions.plugins.module_utils.subactions import Subaction
        from ansible_collections.epfl_si.actions.plugins.module_utils.ansible_api import AnsibleActions
        from ansible.plugins.action import ActionBase

        class MyAction(ActionBase):
            @AnsibleActions.action_run_method
            def run(self, ansible_api):
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

    def __init__ (self, *args, **kwargs):
        self.result = None

        def init_new_calling_convention(self, ansible_api):
            if isinstance(ansible_api, AnsibleActions):
                self.__ansible = ansible_api
            else:
                raise TypeError

        def init_old_calling_convention(self, caller, task_vars):
            """Supported for backwargs compatibility until 1.0 release."""
            self.__ansible = AnsibleActions(caller, task_vars)

        try:
            init_new_calling_convention(self, *args, **kwargs)
        except TypeError:
            init_old_calling_convention(self, *args, **kwargs)

    def query (self, action_name, args):
        """Execute a read-only Ansible sub-action.

        Only a cursory sanity check is performed on `action_name`; this
        method has is no way to tell if e.g. your `command` invocation
        is indeed read-only (although it should be; otherwise consider
        using the `change` method instead).

        If check mode is active (i.e. `ansible-playbook --check`), this action
        will still run.

        :param action_name: Ansible module name to use
        :param args: dict with arguments to give to module
        """
        def run_and_update_result(self):
            query_result = self.__ansible.run_action(action_name, args)
            if self.result is not None:
                AnsibleResults.update(self.result, AnsibleResults.unchanged(query_result))
            self._raise_if_failed(query_result)
            return query_result

        if (self.__ansible.check_mode.is_active and
            self._may_run_in_check_mode(action_name, args)):
            with self.__ansible.check_mode.bypassed:
                return run_and_update_result(self)
        else:
            return run_and_update_result(self)

    def _may_run_in_check_mode (self, action_name, args):
        """True iff this action is safe to run in Ansible's check mode (i.e., it is read only)."""
        return action_name in ("command", "stat")

    def _is_check_mode_active(self):
        """Obsolete, please use ansible_api.AnsibleActions.check_mode.is_active instead."""
        return self.__ansible.check_mode.is_active

    def change (self, action_name, args, update_result=None):
        """Execute an effectful Ansible sub-action.

        If check mode is active (i.e. ansible-playbook --check), nothing
        is done except simulating a change on the Ansible side (“orange”
        condition).

        :param action_name: Ansible module name to use
        :param args: Dict with arguments to give to module
        :param update_result: Obsolete, set the `result` object property instead

        :return: The Ansible result dict for the underlying action if update_result was None;
                 or the (changed) update_result parameter otherwise
        """
        if self.__ansible.check_mode.is_active:
            # Simulate "orange" condition, but don't actually do it
            result = dict(changed=True)
        else:
            result = self.__ansible.run_action(action_name, args)

        if update_result:
            AnsibleResults.update(update_result, result)
            self._raise_if_failed(result)
            return update_result   # Pretty debatable idea - Part of the reason why
                                   # update_result is obsolete
        else:
            if self.result is not None:
                AnsibleResults.update(self.result, result)
            self._raise_if_failed(result)
            return result

    def _raise_if_failed(self, result):
        if 'failed' in result:
            raise AnsibleActionFail("Subaction failed: %s - Invoked with %s" % (
                result.get('msg', '(no message)'),
                result.get('invocation', '(no invocation information)')))
