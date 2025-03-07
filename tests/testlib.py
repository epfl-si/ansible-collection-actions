from functools import cached_property
import logging
import yaml

from unittest.mock import patch, Mock, MagicMock

from ansible.executor.task_executor import TaskExecutor
from ansible.inventory.host import Host
from ansible.inventory.manager import InventoryManager
from ansible.playbook.block import Block
from ansible.playbook.play import Play
from ansible.playbook.play_context import PlayContext
from ansible.playbook.task import Task
from ansible.plugins import loader as ansible_loader
from ansible.plugins.connection import ConnectionBase
from ansible.plugins.connection.local import Connection as LocalConnection
from ansible.plugins.inventory.yaml import InventoryModule as YAMLInventory
from ansible.plugins.loader import PluginLoader, get_with_context_result, PluginLoadContext
from ansible.vars.hostvars import HostVars
from ansible.vars.manager import VariableManager


logging.basicConfig(level=logging.DEBUG)


def yaml_safe_load (thing):
    if isinstance(thing, str):
        return yaml.safe_load(thing)
    else:
        return thing


class MockTaskRunner:
    """Run tasks as Ansible would."""
    def __init__ (self):
        self._on_each_task = []

    def on_each_task (self, callback):
        """Add a thing to do whenever `run_one_task` takes control.

        :param callback: A function that takes an instance of `AnsibleMock`,
        typically to add / change its attributes.
        """
        self._on_each_task.append(callback)

    def inject_actions (self, **actions):
        for name, cls in actions.items():
            def inject_this_action (mock):
                mock.inject_action(name, cls)

            self.on_each_task(inject_this_action)

    def run_one_task (self, task_yaml, vars={}):
        with AnsibleMocker() as mock:
            for todo in self._on_each_task:
                todo(mock)

            # This needs to come *after* the self._on_each_task callbacks
            # have run, because the mock task to create may be an instance
            # of one of the injected actions:
            mock.task = mock.make_task(task_yaml)

            executor = TaskExecutor(
                host=mock.host, task=mock.task,
                job_vars=vars, play_context=mock.play_context,
                new_stdin=None, loader=mock.loader,
                shared_loader_obj=mock.shared_loader_obj,
                final_q=MagicMock(), variable_manager=mock.variable_manager)

            return executor.run()


class AnsibleMocker:
    """The bare minimum of mocking that gets the test suite to pass.

    Instances of this class are meant to be used as a context manager,
    like this:

        with AnsibleMocker() as mock:
            # Do things that invoke Ansible
    """
    # Yes, every single line of code in this indented block was indeed
    # challenged w/ YAGNI or replacing with a MagicMock. Be my guest,
    # try by yourself, run the whole test matrix again, send me a pull
    # request.

    _current = None

    def __init__ (self):
        self._nested = self.__class__._current
        if self._nested:
            return

        self._injected_action_builders = {}

        self.play_context = PlayContext()
        self.loader = MagicMock()
        self.templar = MagicMock()
        self.shared_loader_obj = ansible_loader  # We mock it in __enter__()
        self.inventory = self.InventoryManager()
        self.host = MagicMock()

        self.variable_manager = VariableManager(loader=self.loader, inventory=self.inventory)
        self.hostvars = HostVars(
            inventory=self.inventory,
            variable_manager=self.variable_manager,
            loader=self.loader)

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
        task = Task.load(yaml_safe_load(task_yaml))

        task._connection = 'local'

        # Required to break out of a silly recursion in Task().get_play():
        task._parent = Block()
        task._parent._play = Play()

        return task

    def __enter__ (self):
        if self._nested:
            return self._nested
        else:
            self.__class__._current = self

        self._patches = []

        def empatch (where, new):
            p = patch(where, new=new)
            p.__enter__()
            self._patches.append(p)

        mocked_actions = self.ActionLoader(
            ansible_loader.action_loader, self._injected_action_builders)
        for where in ('ansible.plugins.loader.action_loader',
                      # Some places already did some variation of
                      # `from ansible.plugins.loader import action_loader`
                      # and we have to patch them in-place:
                      'ansible.parsing.mod_args.action_loader'):
                empatch(where, mocked_actions)

        return self

    def __exit__ (self, exn_type=None, exn_value=None, exn_traceback=None):
        if self._nested:
            return

        self.__class__._current = None

        for p in reversed(self._patches):
            p.__exit__(exn_type, exn_value, exn_traceback)

    def inject_action (self, name, cls):
        def construct_action ():
            return cls(
                self.task, self.connection_object, self.play_context,
                self.loader, self.templar,
                self.shared_loader_obj)

        self._injected_action_builders[name] = construct_action

    @cached_property
    def connection_object (self):
        return LocalConnection(PlayContext())

    class ActionLoader (PluginLoader):
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
                return super(AnsibleMocker.ActionLoader, self).find_plugin_with_context(name, *args, **kwargs)
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
                return super(AnsibleMocker.ActionLoader,
                             self).get_with_context(name, *args, **kwargs)

            return get_with_context_result(
                self.injected_action_builders[name](),
                self.mock_plugin_load_context_for_action(name))

    class InventoryManager (InventoryManager):
        """A clone of `ansible.inventory.manager.InventoryManager` that
        reads from mock data in-memory, rather than the file system.

        By default (i.e. after construction) the inventory is entirely
        empty. Call :py:meth:`load_inventory` to populate it.
        """
        mock_inventory_filename = "<test inventory in memory>"

        def __init__ (self):
            super(AnsibleMocker.InventoryManager, self).__init__(
                loader=MagicMock(),
                sources=[self.mock_inventory_filename],
                parse=False,   # We call .parse() ourselves if needed
                cache=False)

        def load_inventory (self, inventory_yaml):
            inventory_struct = yaml_safe_load(inventory_yaml)

            plugin = YAMLInventory()
            plugin._load_name = MagicMock()

            loader = Mock()
            loader.load_from_file = lambda *_, **__: inventory_struct
            loader.get_basedir = lambda : '.'

            plugin.parse(self._inventory, loader,
                         self.mock_inventory_filename, cache=False)


class MockPlay:
    """Run multiple tasks against an inventory, as Ansible would."""
    def __init__ (self, inventory_yaml=None):
        """Constructor.

        :param inventory_yaml: The default value for subsequent calls
                               to :py:meth:`run_tasks`, for the (most
                               common) case where the inventory stays
                               the same during the entire play.
        """
        self._runners = {}
        self._per_runner_callbacks = []
        self._inventory_yaml = inventory_yaml

    def _get_runner (self, inventory_hostname):
        if inventory_hostname not in self._runners:
            runner = MockTaskRunner()
            for callback in self._per_runner_callbacks:
                callback(runner)

            self._runners[inventory_hostname] = runner

        return self._runners[inventory_hostname]

    def _on_each_runner (self, cb):
        self._per_runner_callbacks.append(cb)
        # In case the party's already started:
        for runner in self._runners.values():
            cb(runner)

    def inject_actions (self, **actions):
        def inject_the_actions (runner):
            runner.inject_actions(**actions)

        self._on_each_runner(inject_the_actions)

    def run_tasks(self, tasks_yaml, inventory_yaml=None):
        if inventory_yaml is None:
            inventory_yaml = self._inventory_yaml

        with AnsibleMocker() as mock:
            mock.inventory.load_inventory(inventory_yaml)

            results = []
            for task in yaml_safe_load(tasks_yaml):
                results.append({})

                for host in mock.inventory.list_hosts():
                    inventory_hostname = host.get_name()
                    runner = self._get_runner(inventory_hostname)

                    results[-1][inventory_hostname] = runner.run_one_task(
                        task, vars=mock.variable_manager.get_vars(host=host,
                                                                  include_hostvars=True))

            return results

class AnsibleDebugging:
    """Bits and tricks to help troubleshooting failing tests."""

    @classmethod
    def debug_trace_on (cls):
        return patch('ansible.constants.DEFAULT_DEBUG', True)

    @classmethod
    def assert_task_success (cls, task_state, msg=None):
        if msg is None:
            qualifier = ""
        else:
            qualifier = f"{msg}: "

        if not task_state.get('failed'):
            return

        exn = task_state.get('exception')
        if exn:
            print(exn)
            raise AssertionError(f'{qualifier}Ansible task failed with an exception')
        else:
            raise AssertionError(f'{qualifier}Ansible task failed')
