import unittest
from unittest.mock import patch, Mock
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


def play (inject_actions=dict(do_it=DoIt), inventory_yaml=inventory_yaml):
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

    def describe_jinja_lookup ():
        def _run_action_class (cls):
            [results] = play(inject_actions=dict(do_it=cls),
                            inventory_yaml="""
all:
  hosts:
    h1:
"""
                            ).run_tasks("""
- name: Do it
  do_it: {}
"""
                                        )
            result = results['h1']
            if 'msg' in result:
                print("_run_action_class: Ansible message for task: " + result['msg'])
            return result

        def it_lookups ():
            class LookupSuccessful (ActionBase):
                @AnsibleActions.run_method
                def run (self, args, ansible_api):
                    self.__class__.lookup_result = ansible_api.jinja.lookup("env", "PATH")

            result = _run_action_class(LookupSuccessful)
            assert(len(LookupSuccessful.lookup_result))

        def it_lookups_none ():
            class LookupNonexistent (ActionBase):
                @AnsibleActions.run_method
                def run (self, args, ansible_api):
                    self.__class__.lookup_result = ansible_api.jinja.lookup(
                        "env", "THIS_VAR_NO_EXIST")

            result = _run_action_class(LookupNonexistent)
            assert(LookupNonexistent.lookup_result is None)

        def it_lookups_default ():
            class LookupNonexistent (ActionBase):
                @AnsibleActions.run_method
                def run (self, args, ansible_api):
                    self.__class__.lookup_result = ansible_api.jinja.lookup(
                        "env", "THIS_VAR_NO_EXIST", default="tutu")

            result = _run_action_class(LookupNonexistent)
            assert(LookupNonexistent.lookup_result == "tutu")

        class MockEnvLookup: 
            def __enter__ (self):
                self.run = Mock()
                self._patched = patch("ansible.plugins.lookup.env.LookupModule.run", self.run)
                self._patched.__enter__()
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                patched = self._patched
                del self._patched
                del self.run
                return patched.__exit__(exc_type, exc_val, exc_tb)

        def it_is_robust_with_quoting ():
            tricky_variable_name = "this variable doesn't exist"
            class DoATrickyLookup (ActionBase):
                all_done = False
                @AnsibleActions.run_method
                def run (self, args, ansible_api):
                    assert ansible_api.jinja.lookup("env", tricky_variable_name) == "whatever"
                    self.__class__.all_done = True
                    return {}

            def expect_the_tricky_variable_name (terms, variables, **kwargs):
                assert(terms[0] == tricky_variable_name)
                return ["whatever"]
                
            with MockEnvLookup() as env:
                env.run.side_effect = expect_the_tricky_variable_name

                result = _run_action_class(DoATrickyLookup)
                assert(DoATrickyLookup.all_done)

        def it_does_kwargs ():
            class LookupWithKwargs (ActionBase):
                @AnsibleActions.run_method
                def run (self, args, ansible_api):
                    assert "OK" == ansible_api.jinja.lookup("env", foo="bar")
                    return {}

            def expect_kwargs (terms, variables, **kwargs):
                assert kwargs["foo"] == "bar"
                return ["OK"]

            with MockEnvLookup() as env:
                env.run.side_effect = expect_kwargs

                assert not _run_action_class(LookupWithKwargs)["failed"]

        def it_does_tricky_kwargs ():
            bag_of_tricks={"ye olde 'key": "hasn't got a value"}
            class LookupWithTrickyKwargs (ActionBase):
                @AnsibleActions.run_method
                def run (self, args, ansible_api):
                    assert "OK" == ansible_api.jinja.lookup("env", foo="bar", **bag_of_tricks)
                    return {}

            def expect_kwargs (terms, variables, **kwargs):
                for k, v in bag_of_tricks.items():
                    assert kwargs[k] == v
                return ["OK"]

            with MockEnvLookup() as env:
                env.run.side_effect = expect_kwargs

                assert not _run_action_class(LookupWithTrickyKwargs)["failed"]
