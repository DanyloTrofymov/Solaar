#!/usr/bin/env python3

## Copyright (C) 2012-2013  Daniel Pavel
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License along
## with this program; if not, write to the Free Software Foundation, Inc.,
## 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import argparse
import faulthandler
import importlib
import logging
import os.path
import platform
import signal
import sys
import tempfile

from traceback import format_exc

import solaar.cli as _cli
import solaar.configuration as _configuration
import solaar.i18n as _i18n
import solaar.listener as _listener
import solaar.ui as _ui
import solaar.ui.common as _common
import solaar.upower as _upower

from solaar import NAME, __version__

logger = logging.getLogger(__name__)

#
#
#


def _require(module, os_package, gi=None, gi_package=None, gi_version=None):
    try:
        if gi is not None:
            gi.require_version(gi_package, gi_version)
        return importlib.import_module(module)
    except (ImportError, ValueError):
        sys.exit(f"{NAME.lower()}: missing required system package {os_package}")


battery_icons_style = "regular"
temp = tempfile.NamedTemporaryFile(prefix="Solaar_", mode="w", delete=True)


def _parse_arguments():
    arg_parser = argparse.ArgumentParser(
        prog=NAME.lower(), epilog="For more information see https://pwr-solaar.github.io/Solaar"
    )
    arg_parser.add_argument(
        "-d",
        "--debug",
        action="count",
        default=0,
        help="print logging messages, for debugging purposes (may be repeated for extra verbosity)",
    )
    arg_parser.add_argument(
        "-D",
        "--hidraw",
        action="store",
        dest="hidraw_path",
        metavar="PATH",
        help="unifying receiver to use; the first detected receiver if unspecified. Example: /dev/hidraw2",
    )
    arg_parser.add_argument("--restart-on-wake-up", action="store_true", help="restart Solaar on sleep wake-up (experimental)")
    arg_parser.add_argument(
        "-w", "--window", choices=("show", "hide", "only"), help="start with window showing / hidden / only (no tray icon)"
    )
    arg_parser.add_argument(
        "-b",
        "--battery-icons",
        choices=("regular", "symbolic", "solaar"),
        help="prefer regular battery / symbolic battery / solaar icons",
    )
    arg_parser.add_argument("--tray-icon-size", type=int, help="explicit size for tray icons")
    arg_parser.add_argument("-V", "--version", action="version", version="%(prog)s " + __version__)
    arg_parser.add_argument("--help-actions", action="store_true", help="print help for the optional actions")
    arg_parser.add_argument("action", nargs=argparse.REMAINDER, choices=_cli.actions, help="optional actions to perform")

    args = arg_parser.parse_args()

    if args.help_actions:
        _cli.print_help()
        return

    if args.window is None:
        args.window = "show"  # default behaviour is to show main window

    global battery_icons_style
    battery_icons_style = args.battery_icons if args.battery_icons is not None else "regular"
    global tray_icon_size
    tray_icon_size = args.tray_icon_size

    log_format = "%(asctime)s,%(msecs)03d %(levelname)8s [%(threadName)s] %(name)s: %(message)s"
    log_level = logging.ERROR - 10 * args.debug
    logging.getLogger("").setLevel(min(log_level, logging.WARNING))
    file_handler = logging.StreamHandler(temp)
    file_handler.setLevel(max(min(log_level, logging.WARNING), logging.INFO))
    file_handler.setFormatter(logging.Formatter(log_format))
    logging.getLogger("").addHandler(file_handler)
    if args.debug > 0:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter(log_format))
        stream_handler.setLevel(log_level)
        logging.getLogger("").addHandler(stream_handler)

    if not args.action:
        if logger.isEnabledFor(logging.INFO):
            logger.info("version %s, language %s (%s)", __version__, _i18n.language, _i18n.encoding)

    return args


# On first SIGINT, dump threads to stderr; on second, exit
def _handlesig(signl, stack):
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)

    if signl == int(signal.SIGINT):
        if logger.isEnabledFor(logging.INFO):
            faulthandler.dump_traceback()
        sys.exit(f"{NAME.lower()}: exit due to keyboard interrupt")
    else:
        sys.exit(0)


def main():
    if platform.system() not in ("Darwin", "Windows"):
        _require("pyudev", "python3-pyudev")

    args = _parse_arguments()
    if not args:
        return
    if args.action:
        # if any argument, run comandline and exit
        return _cli.run(args.action, args.hidraw_path)

    gi = _require("gi", "python3-gi (in Ubuntu) or python3-gobject (in Fedora)")
    _require("gi.repository.Gtk", "gir1.2-gtk-3.0", gi, "Gtk", "3.0")

    # handle ^C in console
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGINT, _handlesig)
    signal.signal(signal.SIGTERM, _handlesig)

    udev_file = "42-logitech-unify-permissions.rules"
    if (
        logger.isEnabledFor(logging.WARNING)
        and not os.path.isfile("/etc/udev/rules.d/" + udev_file)
        and not os.path.isfile("/usr/lib/udev/rules.d/" + udev_file)
        and not os.path.isfile("/usr/local/lib/udev/rules.d/" + udev_file)
    ):
        logger.warning("Solaar udev file not found in expected location")
        logger.warning("See https://pwr-solaar.github.io/Solaar/installation for more information")
    try:
        _listener.setup_scanner(_ui.status_changed, _ui.setting_changed, _common.error_dialog)

        if args.restart_on_wake_up:
            _upower.watch(_listener.start_all, _listener.stop_all)
        else:
            _upower.watch(lambda: _listener.ping_all(True))

        _configuration.defer_saves = True  # allow configuration saves to be deferred

        # main UI event loop
        _ui.run_loop(_listener.start_all, _listener.stop_all, args.window != "only", args.window != "hide")
    except Exception:
        sys.exit(f"{NAME.lower()}: error: {format_exc()}")

    temp.close()


if __name__ == "__main__":
    main()
