from functools import cached_property
import logging
import yaml

from unittest.mock import patch, MagicMock

from ansible.executor.task_executor import TaskExecutor
from ansible.inventory.host import Host
from ansible.playbook.block import Block
from ansible.playbook.play import Play
from ansible.playbook.play_context import PlayContext
from ansible.playbook.task import Task
from ansible.plugins import loader as ansible_loader
from ansible.plugins.connection import ConnectionBase
from ansible.plugins.connection.local import Connection as LocalConnection
from ansible.plugins.loader import PluginLoader, get_with_context_result, PluginLoadContext
from ansible.vars.manager import VariableManager


logging.basicConfig(level=logging.DEBUG)


class MockTaskRunner:
    """Run tasks as Ansible would."""
    def __init__ (self):
        self.injected_actions = {}

    def inject_actions (self, **actions):
        self.injected_actions = {**self.injected_actions, **actions}

    def run_one_task (self, task_yaml):
        with RunActionMocker(injected_actions = self.injected_actions) as mock:
            mock.task = mock.make_task(task_yaml)

            executor = TaskExecutor(
                host=mock.host, task=mock.task,
                job_vars={}, play_context=mock.play_context,
                new_stdin=None, loader=mock.loader,
                shared_loader_obj=mock.shared_loader_obj,
                final_q=MagicMock(), variable_manager=mock.variable_manager)

            return executor.run()


class RunActionMocker:
    """The bare minimum of mocking that gets `MockTaskRunner` to pass its tests."""
    # Yes, every single line of code in this indented block was indeed
    # challenged w/ YAGNI or replacing with a MagicMock. Be my guest,
    # try by yourself, run the whole test matrix again, send me a pull
    # request.
    _action_loader_orig = ansible_loader.action_loader

    def __init__ (self, injected_actions={}):
        if ansible_loader.action_loader is not self._action_loader_orig:
            raise TypeError("Illegal MockModuleLoader reentrant call")

        self.injected_actions = injected_actions

    def __enter__ (self):
        self._patches = []

        def empatch (where, new):
            p = patch(where, new=new)
            p.__enter__()
            self._patches.append(p)

        mocked_actions = self.MockActionLoader(
            ansible_loader.module_loader, self._injected_action_builders)
        for where in ('ansible.plugins.loader.action_loader',
                      # Some places already did some variation of
                      # `from ansible.plugins.loader import module_loader`
                      # and we have to patch them in-place:
                      'ansible.parsing.mod_args.action_loader'):
                empatch(where, mocked_actions)

        return self

    @property
    def _injected_action_builders (self):
        """Like `self.injected_actions`, except the dict values are zero-parameter
        functions that call the actual constructors with all their parameters
        mocked out."""

        def construct_action (cls):
            return cls(
                self.task, self.connection_object, self.play_context,
                self.loader, self.templar, self.shared_loader_obj)

        return { name : (lambda : construct_action(cls))
                 for (name, cls) in self.injected_actions.items() }

    @cached_property
    def variable_manager (self):
        return VariableManager(loader=self.loader, inventory=self.inventory)

    @cached_property
    def play_context (self):
        return PlayContext()

    @cached_property
    def inventory (self):
        return MagicMock()

    @cached_property
    def loader (self):
        return MagicMock()

    @cached_property
    def templar (self):
        return MagicMock()

    @property
    def shared_loader_obj (self):
        return ansible_loader

    @cached_property
    def host (self):
        return MagicMock()

    @property
    def task (self):
        try:
            return self._mock_task
        except AttributeError:
            self._logger.warning(
                "Attempt to access `mock.task` before setting it!")
            return MagicMock()

    @task.setter
    def task (self, task):
        self._mock_task = task

    def make_task (self, task_yaml):
        task = Task.load(yaml.safe_load(task_yaml))

        task._connection = 'local'

        # Required to break out of a silly recursion in Task().get_play():
        task._parent = Block()
        task._parent._play = Play()

        return task

    @cached_property
    def connection_object (self):
        return LocalConnection(PlayContext())

    def __exit__ (self, exn_type=None, exn_value=None, exn_traceback=None):
        for p in reversed(self._patches):
            p.__exit__(exn_type, exn_value, exn_traceback)

    class MockActionLoader (PluginLoader):
        def __init__ (self, loader_orig, injected_action_builders):
            super().__init__(
                class_name=loader_orig.class_name,
                package=loader_orig.package,
                config=loader_orig.config,
                subdir=loader_orig.subdir,
                required_base_class=loader_orig.base_class)

            self._logger = logging.getLogger(self.__class__.__name__)
            self.injected_action_builders = injected_action_builders

        def find_plugin_with_context (self, name, *args, **kwargs):
            """Overloaded to let Ansible callers know about our injected actions.

            Returns: A PluginLoadContext instance indicating (among other things) discovery
            status, with fields such as `.resolved`, `.plugin_resolved_path` and `.redirect_list`
            (which for some reason, has to be a non-empty list to indicate an action rather than
            a module; see is_action_candidate logic in ansible.parsing.mod_args.ModuleArgsParser
            class).

            Called
            - by `ansible.parsing._get_action_context()` as part of `ModuleArgsParser().parse()`,
              which wants to know whether it should validate module arguments. (In the case of
              an action plugin, real or injected, it should not);
            - as well as internally by the superclass' `get_with_context` implementation, to work
              out the second member of the tuple it returns (i.e. the context, as per the name).
            """

            if name not in self.injected_action_builders:
                return super(RunActionMocker.MockActionLoader, self).find_plugin_with_context(name, *args, **kwargs)
            return self.mock_plugin_load_context_for_action(name)

        def mock_plugin_load_context_for_action (self, name):
            plc = PluginLoadContext()
            plc.resolved = True
            plc.plugin_resolved_path = f'testlib.{ name }' 
            # Fool is_action_candidate test in class ModuleArgsParser:
            plc.redirect_list = [plc.plugin_resolved_path]
            return plc

        def get_with_context (self, name, *args, **kwargs):
            """Overloaded to return the instance of the action class."""
            if name not in self.injected_action_builders:
                return super(RunActionMocker.MockActionLoader,
                             self).get_with_context(name, *args, **kwargs)

            return get_with_context_result(
                self.injected_action_builders[name](),
                self.mock_plugin_load_context_for_action(name))
