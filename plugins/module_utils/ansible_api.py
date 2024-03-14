"""
Encapsulations for the subset of the Ansible API that is useful when writing action modules.
"""

import inspect

# There is a name clash with a module in Ansible named "copy":
deepcopy = __import__('copy').deepcopy

class AnsibleActions (object):
    """The actions API of Ansible.

    An instance of this class contains all the API that should be
    useful e.g. to a class that derives from
    `ansible.plugins.action.ActionBase`, sans the wonky calling
    conventions and the inheritance-that-breaks-encapsulation.

    Public attributes:

       check_mode: An instance of AnsibleCheckMode
    """
    def __init__ (self, action, task_vars):
        """Constructor.

        Call from the `run` method of your ActionBase subclass, e.g.

            from ansible_collections.epfl_si.actions.plugins.module_utils.ansible_api import AnsibleActions

            def run(self, tmp=None, task_vars=None):
              result = super(ActionModule, self).run(tmp, task_vars)
              api = AnsibleActions(self, task_vars)
              ... Your code goes here...

        Or if you can't be bothered, just use the `run_method` decorator
        to take care of that boilerplate for you.

        Arguments:
           action: The action instance in play (typically belonging to
             your own subclass of `ansible.plugins.action.ActionBase`,
             and that makes use of the `run_method` wrapper)
           task_vars: The variables that Ansible passed to your action
             class. After construction, a `deepcopy` of it will be
             available as the `.task_vars` public attribute.
        """

        self.__caller_action = action
        self.__task_vars = task_vars
        self.check_mode = AnsibleCheckMode(action, task_vars)

    @classmethod
    def run_method (cls, run_method):
        """Boilerplate-free adapter to write your `run` methods.

        Use like this:

            from ansible_collections.epfl_si.actions.plugins.module_utils.ansible_api import AnsibleActions

            @AnsibleActions.run_method
            def run (self, args, ansible_api):
               ...

        Your wrapped `run` method will always be passed the following
        positional arguments:

        args               The task arguments
        ansible_api        An AnsibleActions instance

        Additionnally, your method may decide to accept the following
        named arguments (and they will only be passed if your method
        can accept them):

        result             The result of calling the superclass' `run` method, as
                           an Ansible result dict that may or may not contain a
                           warning about some code you don't control using an
                           obsolete API
        task_vars          The dict of variables that Ansible set for the task
                           currently executing.

        Naturally, using an @run_method decorator won't break the is-a
        relationship, meaning that if you want to access protected
        fields in `self` (instead of, or in addition to calling
        methods on `ansible_api`), you can.
        """
        from ansible.plugins.action import ActionBase

        def wrapped_method (self, task_vars, tmp=None):
            this = cls(self, task_vars)
            task_args = self._task.args

            all_kwargs = dict(
                result=ActionBase.run(self, tmp, task_vars),
                task_vars=task_vars)

            accepted_parameters = cls.__get_optional_parameter_names(run_method)
            kwargs = dict((k, v) for (k, v) in all_kwargs.items()
                                 if k in accepted_parameters)

            result = run_method(self, task_args, this, **kwargs)
            if AnsibleResults.is_instance(result):
                return result
            else:
                raise TypeError("Wrapped @run_method should return an Ansible result dict")

        return wrapped_method

    @staticmethod
    def __get_optional_parameter_names (run_method):
        params = inspect.signature(run_method).parameters
        return set(list(params)[3:])

    def run_action (self, action_name, args, vars=None):
        """Do what it takes with the Ansible API to get it to run the desired action.

        :param action_name: The name of an Ansible action module, whether bundled with Ansible
                            (e.g. "command") or user-provided (as a dynamically-loaded
                            plugin under the `action_plugins` subdirectory of a role or
                            collection)
        :param args: The args that would be passed to this action if we were invoking it
                     the old-fashioned way (i.e., through YAML in a play)

        :param vars: The dict of Ansible vars that the action to run should see. By
                     default, pass “our” vars (the ones passed to the caller).
        :return: The Ansible result dict for the underlying action
        """
        from ansible.errors import AnsibleError
        try:
            # Plan A
            # https://www.ansible.com/blog/how-to-extend-ansible-through-plugins at "Action Plugins"
            return self.__caller_action._execute_module(
                module_name=action_name,
                module_args=args,
                task_vars=vars if vars is not None else self.__task_vars)
        except AnsibleError as e:
            if not e.message.endswith('was not found in configured module paths'):
                raise e

        # Plan B
        # Maybe action_name designates a "user-defined" action module
        # Retry through self._shared_loader_obj
        new_task = self.__caller_action._task.copy()
        new_task.args = deepcopy(args)

        sub_action = self.__caller_action._shared_loader_obj.action_loader.get(
            action_name,
            task=new_task,
            connection=self.__caller_action._connection,
            play_context=self.__caller_action._play_context,
            loader=self.__caller_action._loader,
            templar=self.__caller_action._templar,
            shared_loader_obj=self.__caller_action._shared_loader_obj)
        return sub_action.run(task_vars=self.__task_vars)


class AnsibleCheckMode(object):
    """API for querying / setting Ansible's check mode."""

    def __init__ (self, caller_action, task_vars):
        self.__task_vars = task_vars
        self.__play_context = caller_action._play_context

    @property
    def is_active (self):
        return self.__task_vars.get('ansible_check_mode', False)

    @property
    def bypassed (self):
        """`with` handler for actions that we do want to run, even in check mode.

        Within a `with api.check_mode.bypassed` block, Ansible's check mode is
        temporarily bypassed, so that one can run read-only sub-actions.
        """

        class AnsibleCheckModeBypassed(object):
            def __init__ (self, play_context):
                self.__play_context = play_context

            def __enter__ (self):
                self.__saved_check_mode =  self.__play_context.check_mode
                self.__play_context.check_mode = False  # Meaning that yes, it supports check mode

            def __exit__ (self, *unused_exception_state):
                self.__play_context.check_mode = self.__saved_check_mode

        return AnsibleCheckModeBypassed(self.__play_context)


class AnsibleResults(object):
    """Operations on the Ansible result dicts.

    This is a “pure static” class; it makes no sense to construct instances.
    """
    def __init__ (self):
        raise NotImplementedError(
            "%s is a pure-static class; instances may not be constructed" %
            self.__class__.__name)

    @classmethod
    def empty (cls):
        return {}

    @classmethod
    def update (cls, result, new_result):
        """
        Merge `new_result` into `result` like Ansible would

        :param result: dict to update
        :param new_result: dict to update with
        """
        old_result = deepcopy(result)
        result.update(new_result)

        def _keep_flag_truthy (flag_name):
            if (flag_name in old_result and
                old_result[flag_name] and
                flag_name in result and
                not result[flag_name]
            ):
                result[flag_name] = old_result[flag_name]

        _keep_flag_truthy('changed')
        _keep_flag_truthy('failed')

    @classmethod
    def unchanged (cls, result):
        """Return a copy of `result` without its `changed` key (if any)"""
        result_copy = deepcopy(result)
        if "changed" in result_copy:
            del result_copy["changed"]
        return result_copy

    @classmethod
    def is_instance (cls, result):
        return isinstance(result, dict)
