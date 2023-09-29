# Changelog for epfl_si.actions

## versions 0.3.0: minor feature release

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
