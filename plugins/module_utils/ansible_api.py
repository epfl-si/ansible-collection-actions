"""
Encapsulations for the subset of the Ansible API that is useful when writing action modules.
"""

import inspect
import os

# There is a name clash with a module in Ansible named "copy":
copy = __import__('copy')

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

    def run_action (self, action_name, args, vars=None, defaults={}, overrides={},
                    connection=None, bypass_check_mode=None):
        """Do what it takes with the Ansible API to get it to run the desired action.

        :param action_name: The name of an Ansible action module, whether bundled with Ansible
                            (e.g. "command") or user-provided (as a dynamically-loaded
                            plugin under the `action_plugins` subdirectory of a role or
                            collection)
        :param args: The args that would be passed to this action if we were invoking it
                     the old-fashioned way (i.e., through YAML in a play)

        :param vars: The dict of Ansible vars that the action to run should see. By
                     default, pass “our” vars (the ones passed to the caller).
        :param defaults: A dict of Ansible vars that should be set, unless they are already
                         set by the caller task. Incompatible with `vars`.
        :param overrides: A dict of Ansible vars that should be set, *regardless* of whether
                         they are already set by the caller task. Incompatible with `vars`.
        :param connection: A specific Ansible connection object to use instead of the caller's default one.
        :param bypass_check_mode: If set to True, force Ansible to actually run the task regardless of the current setting for `_ansible_check_mode`.
        :return: The Ansible result dict for the underlying action
        """
        from ansible.errors import AnsibleError

        # Plan A: call an action module
        new_task = self.__caller_action._task.copy()
        if bypass_check_mode:
            new_task.check_mode = False
        new_task.args = copy.deepcopy(args)

        if vars is not None:
            task_vars = vars
        else:
            task_vars = self.__complete_vars(defaults, overrides)

        sub_action = self.__caller_action._shared_loader_obj.action_loader.get(
            action_name,
            task=new_task,
            connection=(connection if connection is not None
                        else self.__caller_action._connection),
            play_context=self.__caller_action._play_context,
            loader=self.__caller_action._loader,
            templar=self.__caller_action._templar,
            shared_loader_obj=self.__caller_action._shared_loader_obj)
        if sub_action:
            return sub_action.run(task_vars=task_vars)

        try:
            # Plan B: call a module i.e. upload and run some Python code (“AnsiballZ”) over the connection
            # https://www.ansible.com/blog/how-to-extend-ansible-through-plugins at "Action Plugins"
            action = copy.copy(self.__caller_action)
            action._task = copy.copy(action._task)
            if bypass_check_mode:
                action._task.check_mode = False
            if connection is not None:
                action._connection = connection
            return action._execute_module(
                module_name=action_name,
                module_args=args,
                task_vars=task_vars)
        except AnsibleError as e:
            if not e.message.endswith('was not found in configured module paths'):
                raise e

        raise AnsibleError("Unknown action or module: %s" % action_name)

    def make_connection (self, **vars_overrides):
        """Load and configure a Connection object like Ansible would.

        The connection's shell (available as the return value's
        protected `._shell` property) will automatically be set to
        the result of `.make_shell(**vars_overrides)`.

        :param **vars_overrides: Variables that you would set on an
        Ansible task that you want to change the connection (or shell) details
        of, e.g. `ansible_connection="oc"`, `ansible_remote_tmp="/tmp"` etc.

        Note that `ansible_python_interpreter` is *not* read out of
        the connection object (as Ansible presumes that that is
        invariable per host). If you want to alter this setting temporarily
        (e.g. to run one local action), then you need to 
        """
        cvars = self.__complete_vars({}, vars_overrides)

        conn_type = cvars.get("ansible_connection")
        if conn_type is None:
            # As seen in ansible.executor.TaskExecutor._get_connection():
            conn_type = self.__caller_action._play_context.connection

        shared_loader_obj = self.__caller_action._shared_loader_obj
        connection, unused = shared_loader_obj.connection_loader.get_with_context(
            conn_type,
            self.__caller_action._play_context,
            None,   # _new_stdin - Whatever *that* is supposed to mean.
            shell=self.make_shell(**vars_overrides),
            task_uuid=self.__caller_action._task._uuid,
            ansible_playbook_pid="%d" % os.getppid())
        if not connection:
            raise AnsibleError("the connection plugin '%s' was not found" %
                               conn_type)

        self.__configure_loaded_object("connection", connection, cvars)
        return connection

    def make_shell (self, **vars_overrides):
        """Load and configure a Shell object like Ansible would.

        :param **vars_overrides: Variables that you would set on an
        Ansible task that you want to change the shell details
        of, e.g. `ansible_remote_tmpdir="/tmp"` etc.
        """
        cvars = self.__complete_vars({}, vars_overrides)

        shell_type = cvars.get('ansible_shell_type', 'sh')

        shared_loader_obj = self.__caller_action._shared_loader_obj
        shell, unused = shared_loader_obj.shell_loader.get_with_context(
            shell_type)
        if not shell:
            raise AnsibleError("the shell plugin '%s' was not found" %
                               shell_type)

        self.__configure_loaded_object("shell", shell, cvars)
        return shell

    def __complete_vars (self, defaults, overrides):
        cvars = {}
        cvars.update(defaults)
        cvars.update(self.__task_vars)
        cvars.update(overrides)
        return cvars

    def __configure_loaded_object (self, kind, obj, cvars):
        from ansible import constants as C
        from ansible.errors import AnsibleError

        # As seen in ansible.executor.TaskExecutor._set_connection_options():
        useful_vars = C.config.get_plugin_vars(kind, obj._load_name)
        obj.set_options(
            task_keys=self.__caller_action._task.dump_attrs(),
            var_options=dict((k, self.expand_var(cvars[k]))
                             for k in useful_vars
                             if k in cvars))

    def has_var (self, var):
        return var in self.__task_vars

    def expand_var (self, var, overrides={}, defaults={}):
        if overrides or defaults:
            from ansible.template import Templar
            templar = Templar(variables=self.__complete_vars(defaults, overrides),
                              loader=self.__caller_action._loader)
        else:
            templar = self.__caller_action._templar
        return templar.template(var)


class AnsibleCheckMode(object):
    """API for querying Ansible's check mode."""

    def __init__ (self, caller_action, task_vars):
        self.__task_vars = task_vars

    @property
    def is_active (self):
        return self.__task_vars.get('ansible_check_mode', False)

def _pure_static (self):
    raise NotImplementedError(
        "%s is a pure-static class; instances may not be constructed" %
        self.__class__.__name__)

class AnsibleResults(object):
    """Operations on the Ansible result dicts.

    This is a “pure static” class; it makes no sense to construct instances.
    """
    __init__ = _pure_static

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
        old_result = copy.deepcopy(result)
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
        result_copy = copy.deepcopy(result)
        if "changed" in result_copy:
            del result_copy["changed"]
        return result_copy

    @classmethod
    def is_instance (cls, result):
        return isinstance(result, dict)
