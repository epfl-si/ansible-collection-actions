"""
Encapsulations for the subset of the Ansible API that is useful when writing action modules.
"""

from collections import namedtuple
from functools import cached_property
import inspect
import itertools
import os
import re

from ansible import constants as C
from ansible.template import Templar, AnsibleUndefined
from ansible.errors import AnsibleUndefinedVariable

# There is a name clash with a module in Ansible named "copy":
copy = __import__('copy')

class AnsibleActions (object):
    """The actions API of Ansible.

    An instance of this class contains all the API that should be
    useful e.g. to a class that derives from
    `ansible.plugins.action.ActionBase`, sans the wonky calling
    conventions, the inheritance-that-breaks-encapsulation, and the
    variables being passed around from method to method for no real
    reason (such as the task variables dict).

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
           task_vars: The dict of variables that Ansible passed to your
             action class. After construction, a `deepcopy` of it (or
             those of a sibling host, if `delegate_to` is in play)
             will be available as the `.jinja.vars` public attribute.

        Public fields:
           jinja: holds an `AnsibleJinja` instance.
           check_mode: holds an `AnsibleCheckMode` instance.
           undelegated: None if the task doesn't have `delegate_to`.
             Otherwise, contains a Delegator object with
             `.undelegated.jinja` being an `AnsibleJinja` instance
             populated with the *original* host's variables (i.e.
             before delegation).
        """

        self.__caller_action = action
        self.jinja = AnsibleJinja(action._loader, task_vars)

        self.undelegated = None
        delegate_to = action._task.delegate_to
        if delegate_to:
            jinja_delegate = self.jinja.delegated_to(delegate_to)
            if jinja_delegate:
                Delegator = namedtuple('Delegator', 'jinja')
                self.undelegated = Delegator(self.jinja)
                self.jinja = jinja_delegate

        self.check_mode = AnsibleCheckMode(action, self.jinja)

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
        :param bypass_check_mode: If set to True, force Ansible to actually run the task regardless of the current setting for `_ansible_check_mode`.

        :param connection: OBSOLETE — An Ansible connection object. 💡
                           This is no longer required; overriding
                           `ansible_connection`, `ansible_user` etc.
                           using the `vars` or `overrides` parameters,
                           now has the same effect.

        :return: The Ansible result dict for the underlying action

        """
        from ansible.errors import AnsibleError

        if vars is not None:
            sub_jinja = self.jinja
        else:
            sub_jinja = self.jinja.complete_vars(
                defaults=defaults, overrides=overrides)

        if connection is None:
            if self._need_new_connection(sub_jinja):
                connection = self.make_connection(**sub_jinja.vars)
            else:
                connection = self.__caller_action._connection

        subtask = self.__caller_action._task.copy()
        subtask.action = action_name
        if bypass_check_mode:
            subtask.check_mode = False
        subtask.args = copy.deepcopy(args)
        # The “delegate_to” buck stops here. That is, if the caller
        # task is delegated, we are already “running on” the
        # delegate's substituted variables, including e.g.
        # `ansible_connection`, `ansible_user` etc.
        #
        # There is no need for the
        # `ansible.plugins.action.ActionBase._configure_module` method
        # to muddy the waters by attempting that substitution again.
        # That would be a no-op at best; and in the case where we are
        # being passed a custom `connection` object, it would be
        # ignored outright (as the relevant variables would revert to
        # their values from `ansible_delegated_vars`).
        subtask.delegate_to = None

        # Plan A: call an action module
        sub_action = self.__caller_action._shared_loader_obj.action_loader.get(
            action_name,
            task=subtask,
            connection=connection,
            play_context=self.__caller_action._play_context,
            loader=self.__caller_action._loader,
            templar=self.__caller_action._templar,
            shared_loader_obj=self.__caller_action._shared_loader_obj)
        if sub_action:
            return sub_action.run(task_vars=sub_jinja.vars)

        try:
            # Plan B: call a module i.e. upload and run some Python code (“AnsiballZ”) over the connection
            # https://www.ansible.com/blog/how-to-extend-ansible-through-plugins at "Action Plugins"
            action = copy.copy(self.__caller_action)
            action._task = subtask
            action._connection = connection
            return action._execute_module(
                module_name=action_name,
                module_args=args,
                task_vars=sub_jinja.vars)
        except AnsibleError as e:
            if not e.message.endswith('was not found in configured module paths'):
                raise e

        raise AnsibleError("Unknown action or module: %s" % action_name)

    def _need_new_connection (self, other_jinja):
        """True “iff” `other_vars` requires making a new connection.

        The scare quotes around “iff” mean that the returned Boolean
        is an (upper) approximation of that statement. That is, when
        in doubt, `_need_new_connection()` will err on the side of
        caution and return True. The cost thereof is only inefficiency
        (as in, missing the opportunity of re-using an open
        connection), whereas the cost of erring in the opposite
        direction would be incorrectness (as in, running, or
        attempting to run the task in the wrong place).
        """
        vars1 = self.jinja.vars
        vars2 = other_jinja.vars

        for k in itertools.chain(vars1.keys(), vars2.keys()):
            if vars1.get(k, None) != vars2.get(k, None):
                if k.startswith("ansible_"):  # We could be smarter here, and err less.
                    return True

        return False

    def make_connection (self, **vars_overrides):
        """OBSOLETE public API, do not call directly.

        Load and configure a Connection object like Ansible would.

        The connection's shell (available as the return value's
        protected `._shell` property) will automatically be set to
        the result of `.make_shell(**vars_overrides)`.

        :param **vars_overrides: Variables that you would set on an
        Ansible task that you want to change the connection (or shell) details
        of, e.g. `ansible_connection="oc"`, `ansible_remote_tmp="/tmp"` etc.

        Note that `ansible_python_interpreter` is *not* read out of
        the connection object (as Ansible assumes that that is
        invariable per host). If you want to alter this setting temporarily
        (e.g. to run one local action), then you need to pass that variable
        to `run_action` as well.
        """
        jinja = self.jinja.complete_vars(overrides=vars_overrides)

        conn_type = jinja.vars.get("ansible_connection")
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

        # As seen in ansible.executor.TaskExecutor._set_connection_options():
        var_options = {}
        for k in C.config.get_plugin_vars('connection', conn_type):
            if k in jinja.vars:
                var_options[k] = jinja.expand('{{ %s }}' % k)
        connection.set_options(
            task_keys=self.__caller_action._task.dump_attrs(),
            var_options=var_options)

        return connection

    def make_shell (self, **vars_overrides):
        """OBSOLETE public API, do not call directly.

        Load and configure a Shell object like Ansible would.

        :param **vars_overrides: Variables that you would set on an
        Ansible task that you want to change the shell details
        of, e.g. `ansible_remote_tmpdir="/tmp"` etc.
        """
        jinja = self.jinja.complete_vars(overrides=vars_overrides)

        shell_type = jinja.expand('{{ ansible_shell_type | default("sh") }}')

        shared_loader_obj = self.__caller_action._shared_loader_obj
        shell, unused = shared_loader_obj.shell_loader.get_with_context(
            shell_type)
        if not shell:
            raise AnsibleError("the shell plugin '%s' was not found" %
                               shell_type)

        return shell

    def has_var (self, var):
        return var in self.jinja.vars

    def expand_var (self, var, overrides={}, defaults={}):
        """OBSOLETE, use `.jinja.expand` instead."""
        return self.jinja.complete_vars(
            defaults=defaults, overrides=overrides).expand(var)

__not_set = object()


class AnsibleJinja (object):
    """Easy access to Ansible's Jinja expansion and lookup features.

    Encapsulates an Ansible `Templar` instance, with its bag of Ansible
    variables.
    """

    def __init__ (self, loader, vars):
        self.loader = loader
        self.vars = copy.deepcopy(vars)

    @cached_property
    def _templar (self):
        return Templar(self.loader, self.vars)

    def complete_vars (self, defaults={}, overrides={}):
        """Complete Jinja variables and return a new object.

        Arguments:
          overrides: Variables that should be set, regardless of their
            current values in `self.vars`
          defaults: Variables to set only if they aren't currently set
            in `self.vars` (nor in `overrides` if both parameters are passed
            at the same time)

        Returns: A copy of self with the `.vars` changed as specified;
          or just `self` if the changes have no effect.
        """
        if not (overrides or defaults):
            return self

        cvars = {}
        cvars.update(defaults)
        cvars.update(self.vars)
        cvars.update(overrides)
        return self.__class__(self.loader, cvars)

    def expand (self, expr, **templar_kwargs):
        try:
            return self._templar.template(expr, **templar_kwargs)
        except AnsibleUndefinedVariable as e:
            e.message = 'in expression %s: %s' % (expr, e.message)
            raise e

    def lookup (self, lookup_plugin_name, *lookup_args, **lookup_kwargs):
        # Let's face it, the design of the `lookup` Jinja function is
        # terrible, even by Ansible standards.

        none_surrogate = object()
        if "default" not in lookup_kwargs:
            lookup_kwargs["default"] = none_surrogate

        retval = self._templar._lookup(lookup_plugin_name, *lookup_args, **lookup_kwargs)

        return None if retval is none_surrogate else retval

    def delegated_to (self, delegate_to):
        hostvars = self.vars["hostvars"]
        delegated_vars = hostvars[delegate_to]
        if isinstance(delegated_vars, AnsibleUndefined):
            return None

        delegated_vars_dict = copy.deepcopy(delegated_vars._vars)
        return self.__class__(self.loader, delegated_vars_dict)


class AnsibleCheckMode(object):
    """API for querying Ansible's check mode."""

    def __init__ (self, caller_action, jinja):
        self.__jinja = jinja

    @property
    def is_active (self):
        return self.__jinja.expand('{{ ansible_check_mode | default(False) }}')


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

        def _merge_boolean_with_or (flag_name):
            if (flag_name in old_result and
                old_result[flag_name] and
                flag_name in result and
                not result[flag_name]
            ):
                result[flag_name] = old_result[flag_name]

        _merge_boolean_with_or('changed')
        _merge_boolean_with_or('failed')

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
