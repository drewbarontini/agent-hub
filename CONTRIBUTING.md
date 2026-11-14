# Contributing

Agent Hub favors a small, inspectable Core. Reuse Git, provider-native functionality
and the Python standard library before adding infrastructure.

Use Python 3.11+ on macOS or Linux. Before submitting a change:

```sh
python3.13 -m unittest discover -s tests -v
python3.13 bin/hub secrets
python3.13 bin/hub secrets --staged
```

Use disposable repositories for lifecycle and destructive-operation tests. Do not
run fixture cleanup against real work. Test security-sensitive failures, not just
success paths. Report native runtime tests separately from mocked session lifecycle
tests. Update docs when adding behavior or changing limitations.

Do not include private Instance config, context, logs, org-owned code or designs,
credentials, personal paths or repository lists in Core changes. Generalize only
with ownership and disclosure authorization. See docs/evolution.md before proposing
an Instance-derived feature. No automatic publication is part of this workflow.

All contributions must be compatible with the MIT license. Do not claim rights you
do not have. Obtain the appropriate owner's approval before external submission.

