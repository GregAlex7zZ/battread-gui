# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bundled worker entry retaining standard streams and the parent's ready gate."""

from battread_gui.worker import main

if __name__ == "__main__":
    raise SystemExit(main())
