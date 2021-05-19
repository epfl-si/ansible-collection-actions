#!/usr/bin/env python3
# -*- coding: utf-8; -*-

"""
OO encapsulation of the Ansible control flow.

Writing your Ansible action modules as subclasses of Postcondition lets you
pretty much do away with learning what an Ansible return dict is.
"""

from ansible.errors import AnsibleError, AnsibleActionFail
from ansible.module_utils import six
from ansible_collections.epfl_si.actions.plugins.module_utils.ansible_api import AnsibleResults


class DeclinedToEnforce (AnsibleError):
    """Raised to indicate that no attempt to `enforce` a postcondition was made.

    Raise this postcondition from the `enforce` method to indicate that it
    is not able or not willing to change the state so that the postcondition
    holds. **Do not raise after attempting any state change.**
    """

    def __init__ (self, why=None):
        self.why = why


class Postcondition (object):
    """An Ansible action guarded by a postcondition.

    This class is an abstract base class. To use it, you should
    inherit from it and override some methods (see individual method
    docstrings for more). Instances of your derived class shall
    represent a **postcondition**, i.e. an Ansible task described by
    separating what we want to hold (in the `holds` method), and what
    to do in case it doesn't (the `enforce` method). There is more to
    the API (and you may want to override more methods); but even if
    you don't, the call sequence of these two defines the Ansible
    “traffic light colors” in a straightforward fashion, i.e.

    - if `holds` returns True when first called, the Ansible task goes
      green and `enforce` is not called;
    - otherwise `enforce` will be called; it it runs to completion
      (without throwing), the Ansible task goes yellow;
    - if an exception is thrown anywhere (or if `holds` returns False,
      but you didn't override `enforce`), then the Ansible task
      will be red.
    """
        

    def holds (self):
        """Whether the postcondition currently holds true.

        This method is intended to be overriden in a subclass (see below).

        Returns a truthy value to indicate that the postcondition is
        currently true (and therefore that `enforce` should not run,
        and the Ansible result should be green), or a falsy value
        to indicate that `enforce` should run now (and that the
        Ansible result should be yellow, once the latter succeeds).

        The default behavior is that the postcondition never holds,
        meaning that Ansible will never go green on your task.
        This is very rarely what you want (an example of it being
        what you want would be sending an email or updating
        some kind of monitoring system at the end of a play); in
        all other cases, you need to override the method in a
        subclass.
        """
        return False

    def enforce (self):
        """Make the postcondition be true.

        This method is intended to be overriden in a subclass. The
        default behavior is to do nothing and give up immediately
        (herefore, your overridden method should not call super()).
        Overridden implementations should attempt to set the
        postcondition, or raise an error trying.

        If `enforce()` returns something, it will be used as the
        `result["changed"]` value for the Ansible result dict (meaning
        that `enforce` can return False to indicate that we should
        have an Ansible green, after all)
        """
        raise DeclinedToEnforce("enforcement not implemented")

    def explainer (self):
        """Returns a short string explaining what this postcondition is about.

        Should return a short string that will be pretty-printed in
        warnings or error messages such as "<explainer>: does not
        hold" or "<explainer>: enforcement declined"

        The default implementation simply returns the postcondition class' name.
        """
        return self.__class__.__name__

    def recheck (self):
        """Call holds() again, and this time it better return True.

        Call from within enforce() at the end, if you
        are unable to deduce whether enforce() was
        successful from the information you have.
        """
        if not self.holds():
            raise AnsibleActionFail("%s: still doesn't hold after attempt to enforce" %
                                    self.explainer())

    def passive (self):
        """If truthy, prevent `enforce` from running.

        Override this method in your subclass to shy out of running
        `enforce` (the return value should be the reason as a string).
        **This will turn all Ansible yellows into reds.**

        This is intended for when running `enforce` might be dangerous
        to attempt (e.g. a git rebase), and your action class wants to
        provide configuration to selectively disengage the enforcement
        phase (e.g. in production).

        The base class is always active, i.e. the method returns None.
        """
        return None


def run_postcondition (postcondition, check_mode):
    result = AnsibleResults.empty()

    if postcondition.holds():
        return result  # Green

    passive = postcondition.passive()
    if passive:
        result["failed"] = True
        result["msg"] = (passive if isinstance(passive, six.string_types)
                            else "%s: does not hold" % postcondition.explainer())
        return result  # Red

    if check_mode.is_active:
        result["changed"] = "%s: does not hold; enforcement skipped under --check" % \
          postcondition.explainer()
        return result  # Yellow

    try:
        changed = postcondition.enforce()
        result["changed"] = changed if changed is not None else True
    except DeclinedToEnforce as e:
        result["failed"] = True
        result["msg"] = "%s: %s" % (
            postcondition.explainer(),
            e.why if e.why is not None else "enforcement declined")

    return result  # Yellow or red, depennding on whether we took the except branch

    # Throwing sets red, as it always does
