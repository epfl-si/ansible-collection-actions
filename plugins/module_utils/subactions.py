# There is a name clash with a module in Ansible named "copy":
deepcopy = __import__('copy').deepcopy

from ansible.errors import AnsibleActionFail, AnsibleError

class Subaction(object):
    """Models an Ansible action that your own action module invokes to perform its job.

    The following example supports `ansible-playbook --check` without further ado:

        from ansible_collections.epfl_si.actions.plugins.module_utils.subactions import Subaction
        from ansible.plugins.action import ActionBase

        class MyAction(ActionBase):
            def run(self, tmp=None, task_vars=None):
                self.result = {}
                a = SubAction(caller=self, task_vars=task_vars)
                probe_result = a.query("command",
                                       dict(_raw_params="ls",
                                            chdir="/etc/apache2"))

                # Ponder probe_result...
                return a.change("command",
                                dict(_raw_params="touch",
                                     chdir="/etc/apache2")),
                                update_result=self.result)

    """
    def __init__ (self, caller, task_vars):
        self.__caller_action = caller
        self.__task_vars = task_vars

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
        if (self._is_check_mode_active() and
            self._may_run_in_check_mode(action_name, args)):
            with self._AnsibleCheckModeBypassed(self.__caller_action._play_context):
                return self.__run(action_name, args)
        else:
            return self.__run(action_name, args)

    def _may_run_in_check_mode (self, action_name, args):
        """True iff this action is safe to run in Ansible's check mode (i.e., it is read only)."""
        return action_name in ("command", "stat")

    def _is_check_mode_active(self):
        return self.__task_vars.get('ansible_check_mode', False)            

    class _AnsibleCheckModeBypassed(object):
        """Temporarily bypass Ansible's check mode handling mechanism,
        so that we still run read-only sub-actions while in check mode.
        """
        def __init__(self, play_context):
            self.__play_context = play_context

        def __enter__(self):
            self.__saved_check_mode =  self.__play_context.check_mode
            self.__play_context.check_mode = False  # Meaning that yes, it supports check mode

        def __exit__(self, *unused_exception_state):
            self.__play_context.check_mode = self.__saved_check_mode

    def change (self, action_name, args, update_result=None):
        """Execute an effectful Ansible sub-action.

        If check mode is active (i.e. ansible-playbook --check), nothing
        is done except simulating a change on the Ansible side (“orange”
        condition).

        :param action_name: Ansible module name to use
        :param args: Dict with arguments to give to module
        :param update_result: If set, update this result dict with the status of
           the sub-action

        :return: The Ansible result dict for the underlying action if update_result was None;
                 or the (changed) update_result parameter otherwise
        """
        if self._is_check_mode_active():
            # Simulate "orange" condition, but don't actually do it
            result = dict(changed=True)
        else:
            result = self.__run(action_name, args, update_result=update_result)
        if update_result:
            return update_result
        else:
            return result

    def __run (self, action_name, args, update_result=None):
        caller_action = self.__caller_action

        result = self.__run_with_ansible_api(action_name, args,
                                             self.__caller_action, self.__task_vars)
        if update_result is not None:
            self._update_result(update_result, result)

        if 'failed' in result:
            raise AnsibleActionFail("Subaction failed: %s - Invoked with %s" % (
                result.get('msg', '(no message)'),
                result.get('invocation', '(no invocation information)')))
        else:
            return result

    @staticmethod
    def __run_with_ansible_api (action_name, args, caller_action, task_vars):
        """Do what it takes with the Ansible API to get it to run the desired action.

        This the only place in the entire Python package where we call Ansible code.
        This is a static method, so as to ensure that all parameters are passed explicitly.

        :param action_name: The name of an Ansible action module, whether bundled with Ansible
                            (e.g. "command") or user-provided (as a dynamically-loaded
                            plugin under the `action_plugins` subdirectory of a role or
                            collection)
        :param args: The args that would be passed to this action if we were invoking it
                     the old-fashioned way (i.e., through YAML in a play)
        :param caller_action: An instance of ansible.plugins.action.ActionBase
        :param task_vars: The parameter of the same name received by the ActionBase's `run()` method

        :return: The Ansible result dict for the underlying action
        """
        try:
            # Plan A
            # https://www.ansible.com/blog/how-to-extend-ansible-through-plugins at "Action Plugins"
            return caller_action._execute_module(
                module_name=action_name,
                module_args=args,
                task_vars=task_vars)
        except AnsibleError as e:
            if not e.message.endswith('was not found in configured module paths'):
                raise e

        # Plan B
        # Maybe action_name designates a "user-defined" action module
        # Retry through self._shared_loader_obj
        new_task = caller_action._task.copy()
        new_task.args = deepcopy(args)

        sub_action = caller_action._shared_loader_obj.action_loader.get(
            action_name,
            task=new_task,
            connection=caller_action._connection,
            play_context=caller_action._play_context,
            loader=caller_action._loader,
            templar=caller_action._templar,
            shared_loader_obj=caller_action._shared_loader_obj)
        return sub_action.run(task_vars=task_vars)

    def _update_result (self, result, new_result):
        """
        Merge `new_result` into `result` like Ansible would

        :param result: dict to update
        :param new_result: dict to update with
        """
        old_result = deepcopy(result)
        result.update(new_result)

        def _keep_flag_truthy(flag_name):
            if (flag_name in old_result and
                old_result[flag_name] and
                flag_name in result and
                not result[flag_name]
            ):
                result[flag_name] = old_result[flag_name]

        _keep_flag_truthy('changed')
        _keep_flag_truthy('failed')
