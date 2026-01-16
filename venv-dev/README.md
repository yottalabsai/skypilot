# SkyPilot Development Environment

This is a development virtual environment for contributing to the Yotta integration in SkyPilot.

## Usage

```bash
# Activate the dev environment
source venv-dev/bin/activate

# Run SkyPilot commands
sky launch --cloud yotta examples/minimal.yaml

# Deactivate when done
deactivate
```

## Why separate environment?

As a contributor working on a fork, this dev environment isolates changes from your system-installed SkyPilot:
- ✅ Changes to code take effect immediately (editable install)
- ✅ System SkyPilot remains unaffected
- ✅ Can test Yotta integration without conflicts
- ✅ Uses separate `~/.sky/` configuration

## Development workflow

1. Make code changes in `sky/clouds/yotta.py` or `sky/provision/yotta/`
2. Changes are immediately active (no reinstall needed)
3. Test with: `sky launch --cloud yotta <yaml>`
4. Create catalog: populate `~/.sky/catalogs/v7/yotta/vms.csv`
