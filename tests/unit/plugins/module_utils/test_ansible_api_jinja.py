import unittest
from tests.testlib import MockPlay, AnsibleDebugging

from ansible_collections.epfl_si.actions.plugins.module_utils.subactions import AnsibleActions, AnsibleResults
from ansible.plugins.action import ActionBase

inventory_yaml = """
all:
  hosts:
    h1:
      v: 1
    h2:
      v: 2
"""


def do_it_task_yaml (delegate_to=None):
    returned_yaml = """
- name: Do it
  do_it: {}
"""
    if delegate_to is not None:
        returned_yaml = returned_yaml + f"  delegate_to: {delegate_to}\n"

    return returned_yaml


class DoIt (ActionBase):
    @AnsibleActions.run_method
    def run (self, args, ansible_api):
        return dict(v = ansible_api.jinja.expand('{{ v }}'))


def play (inject_actions=dict(do_it=DoIt)):
    p = MockPlay(inventory_yaml=inventory_yaml)
    p.inject_actions(**inject_actions)
    return p


def describe_ansible_api_jinja_field ():
    def it_expands_v ():
        [result] = play().run_tasks(do_it_task_yaml())

        assert result["h1"]["v"] == 1

    def it_provides_a_helpful_message_upon_undefined_expand ():
        class OopsWrongVar (ActionBase):
            @AnsibleActions.run_method
            def run (self, args, ansible_api):
                return dict(oops = ansible_api.jinja.expand('{{ oops }}'))

        [result] = play({"oops": OopsWrongVar}).run_tasks("""
- name: Do it
  oops: {}
""")
        assert "oops" not in result["h1"]
        assert "in expression {{ oops }}" in result["h1"]["msg"]

    def it_delegates ():
        [result] = play().run_tasks(do_it_task_yaml(delegate_to="h2"))
        for host in ["h1", "h2"]:
            AnsibleDebugging.assert_task_success(
                result[host],
                f'result["{host}"]')
        assert result["h1"]["v"] == 2, "h1"
        assert result["h2"]["v"] == 2, "h2"

    def it_has_undelegated_jinja ():
        class NotEisenhower (ActionBase):
            """It doesn't `delegate_to:`."""
            @AnsibleActions.run_method
            def run (self, args, ansible_api):
                return dict(v = ansible_api.undelegated.jinja.expand('{{ v }}'))

        [result] = play(inject_actions=dict(do_it=NotEisenhower)).run_tasks(
            do_it_task_yaml(delegate_to="h2"))
        for host in ["h1", "h2"]:
            AnsibleDebugging.assert_task_success(
                result[host],
                f'result["{host}"]')
        assert result["h1"]["v"] == 1
        assert result["h2"]["v"] == 2

    def it_always_has_undelegated ():
        """`ansible_api.undelegated` is always set (albeit to None, when `delegate_to:`
        is not set)."""
        class ChecksUndelegated (ActionBase):
            @AnsibleActions.run_method
            def run (self, args, ansible_api):
                assert ansible_api.undelegated is None
                return dict(found_undelegated=True)

        [result] = play(inject_actions=dict(do_it=ChecksUndelegated)).run_tasks(
            do_it_task_yaml())
        for host in ["h1", "h2"]:
            AnsibleDebugging.assert_task_success(
                result[host],
                f'result["{host}"]')
        assert result["h1"]["found_undelegated"]
        assert result["h2"]["found_undelegated"]

    def it_has_hostvars_in_undelegated_jinja ():
        class ChecksHostvarsInUndelegated (ActionBase):
            @AnsibleActions.run_method
            def run (self, args, ansible_api):
                assert "hostvars" in ansible_api.undelegated.jinja.vars
                return dict(found_hostvars=True)

        [result] = play(inject_actions=dict(do_it=ChecksHostvarsInUndelegated)).run_tasks(
            do_it_task_yaml(delegate_to="h2"))
        for host in ["h1", "h2"]:
            AnsibleDebugging.assert_task_success(
                result[host],
                f'result["{host}"]')
        assert result["h1"]["found_hostvars"]
        assert result["h2"]["found_hostvars"]

    def it_ignores_bogus_delegations ():
        [result] = play().run_tasks(do_it_task_yaml(delegate_to="someone_else"))
        for host in ["h1", "h2"]:
            AnsibleDebugging.assert_task_success(
                result[host],
                f'result["{host}"]')
        assert result["h1"]["v"] == 1
        assert result["h2"]["v"] == 2
