#!/bin/sh
# The package is installed outside site-packages, so it needs to be on the
# path explicitly. PyGObject comes from the runtime and must stay findable,
# hence appending rather than replacing.
PYTHONPATH="/app/lib/r2wa${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH
exec python3 -m r2wa.main "$@"
