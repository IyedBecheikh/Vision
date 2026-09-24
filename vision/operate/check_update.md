# Check for Updates

Run the installed lifecycle CLI:

```text
python3 {{VISION_HOME}}/runtime/workflow.py check-update --json
```

Treat this as an explicit, read-only check regardless of the automatic
update-check setting. Expect it to compare the installed version with all
available release assets, report every newer version, and include a compact
summary of each version's GitHub release notes. Keep workflow files unchanged.

If an update is available, review the reported summaries and then send
`vision --update` when you are ready to install the latest release.
