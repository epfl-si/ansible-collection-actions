import unittest
from tests.testlib import MockPlay

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
        [result] = play().run_tasks("""
- name: Do it
  do_it: {}
""")

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
