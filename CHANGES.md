# Changelog for epfl_si.actions

## version 2.2.0: major feature release

- Actions decorated with `@AnsibleAction.run_method` now support Ansible's `delegate_to` feature out-of-the-box. That is, `run_method` constructs their `ansible_api.jinja` out of the Ansible vars fetched from `hostvars` by the `delegate_to` YAML field. For the (supposedly rare) case where the task want to peek at or use the “undelegated” variables, they are accessible through `ansible_api.undelegated.jinja`.

## version 2.1.0: major feature release

- When calling `run_action`, Ansible variables that require setting up a new connection object (such as `ansible_connection`, `ansible_user`) etc. (conservatively and) automatically cause a new connection to be created. It follows that the `make_connection` and `make_shell` APIs are obsolete.
- Introduce API to reify the Jinja machinery (accessible as the `.jinja` field of `AnsibleActions` instances)
- Make exception messages (in particular, when using `.jinja.expand()` easier to debug
- Introduce the first unit tests!!

## version 2.0.2: minor bugfix release

- Fix the case of `delegate_to:` tasks calling action plugins that in turn, pass a custom `connection` object to `run_action`

## version 2.0.1: minor feature release

- Introduce `ansible_api.has_var()` method
- Add `defaults` and `overrides` parameters to `run_action()` method; fix `vars` parameter of same in some cases
- Ability to pass supplemental parameters to `ansible_api.run_action()` through the `Subaction` class

## version 2.0.0: breaking API change

- `Subactions` constructor no longer accepts `task_vars` as an argument
- `shell` may be used in a `query` subaction under the same caveats as `command`

## version 1.1.0: major bugfix and minor feature release

- When an action (such as `ansible.builtin.copy`) shadows a module (i.e. the core of an AnsiballZ) with the same name, we want to run the former rather than the latter. Previous versions did the incorrect thing, i.e. the other way around.
- Ability to pass `defaults` to `ansible_api.expand_var()`, which is basically the opposite of `overrides` priority-wise (i.e. values in `defaults` “underride” the user-set variables)

## version 1.0.0: breaking API change

... and also I guess it was time for an 1.0 release.

- `with AnsibleCheckMode(...).bypassed` is no longer supported, because it no longer works (... since 2019).
- As a replacement, `run_action()` now has a `bypass_check_mode` optional parameter, which the `Subaction()` class sets on subaction invocations that credibly have no effect (i.e. `stat` and `command`, and then only when called with `.query()`)

## version 0.4.0: minor feature and deprecation release

- Drop support for Python 2. Version 0.3.1 is the last version that supports Python 2.
- Provide `ansible_api.expand_var()` to encapsulate the Jinja business (a.k.a. `templar` in the Ansible source code)
- Tasks written on top of `epfl_si.actions.plugins.module_utils.ansible_api` may now observe variables (using the new optional argument `task_vars` to the decorated `run()` method), and change them before passing them to `ansible_api.run_action()`
- Likewise, tasks may now create connections with customized Ansible variables by calling the `ansible_api.make_connection()` method and/or the `ansible_api.make_shell()` method, which the former invokes indirectly.

## version 0.3.1: minor bugfix release

In 0.3.0, we forgout about `run_postcondition()` also being helpful to call from an AnsiballZ context. It now accepts both an `AnsibleCheckMode` instance and a plain old Boolean as its second argument.

## version 0.3.0: minor feature release

- The `ansible_collections.epfl_si.actions.plugins.module_utils.ansible_api` and `ansible_collections.epfl_si.actions.plugins.module_utils.postconditions` modules now support being imported as part of an AnsiballZ package (i.e., from a `library` module that gets sent over the wire to the remote Python interpreter)

## versions 0.2.1 and 0.2.2: minor bugfix releases

- Various documentation and `galaxy.yml` improvements, dead code removal

## version 0.2.0: major feature release

Deprecations / API changes:
- The `update_result` parameter to `Subaction(...).change` is deprecated; instead, one should set the `Subaction(...).result` object field to an Ansible result dict, that will be updated *both* by `.query` and `.change`
- The `Subaction` constructor now takes an `AnsibleActions` API helper (but it still accepts `.run()`-style arguments as well for backwards compatibility)

The grace period for these deprecations will end when version 1.0.0 is released. Please update your code with the new APIs.

New features:
- New `ansible_collections.epfl_si.actions.plugins.module_utils.ansible_api` module, featuring the `AnsibleActions` class (mentioned above); an `@AnsibleActions.run_method` decorator; and the `AnsibleResults` “pure static” class. When used together, these classes and decorator abstract away the unpleasant details of the Ansible architecture (or lack thereof) into more palatable (and sustainable) APIs, even for consumer code that doesn't want to use the `Subaction` class.
- New `ansible_collections.epfl_si.actions.plugins.module_utils.postcondition` module, letting you write Ansible action modules whose behavior is split into *postcondition* (how to know if there is anything to do in the first place) and *enforcement* (how to actually do it). Using the `Postcondition` abstract base class, one can write useful and correct (w.r.t. “colors” and `--check` support) Ansible action modules with a lot less pre-requisite knowledge about the Ansible return dict or the rest of the Ansible API.
- `Subaction(...).query` and `Subaction(...).change` both take a new `failed_when=` optional parameter

Bugfixes:
- When passing (obsolete, see above) `update_result` parameter to `.change()`, also update it if it is falsy (empty)
