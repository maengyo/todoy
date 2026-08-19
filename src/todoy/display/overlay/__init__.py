"""Desktop overlay: a floating reminder character, decoupled from any one OS.

`core` holds pure scheduling/message logic (no AppKit imports, fully unit
tested). `base` defines the OS-agnostic backend contract and the
`create_backend()` factory. `macos` is the pyobjc/AppKit implementation,
imported lazily so importing this package never requires pyobjc.
"""

from __future__ import annotations
