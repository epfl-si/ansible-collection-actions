"""Test the test suite."""

import unittest

from ansible.plugins.action import ActionBase
from tests.testlib import MockTaskRunner, AnsibleMocker

class MyPrintAction(ActionBase):
    def run(self, tmp=None, task_vars=None):
        message = task_vars.get('message', 'Default Message')
        display.display(f"Message: {message}")
        return {"changed": False, "message": message}


class MySumAction(ActionBase):
    def run(self, tmp=None, task_vars=None):
        a = self._task._args['a']
        b = self._task._args['b']
        return {"changed": False, "sum": a + b}

def describe_the_test_suite ():
    def it_runs_actions ():
        task_yaml = """
name: Test Sum
sum:
  a: 1
  b: 2
"""

        runner = MockTaskRunner()
        runner.inject_actions(sum=MySumAction)
        result = runner.run_one_task(task_yaml)
        assert result["sum"] == 3

    def it_does_the_reentrant ():
        """Entering a `with AnsibleMocker()` block twice, re-uses the
        outermost instance.

        This allows for one entry point of testlib to be implemented
        in terms of another, both having a `with AnsibleMocker()` block
        at their core.
        """
        with AnsibleMocker() as m1:
            with AnsibleMocker() as m2:
                assert m1 is m2
