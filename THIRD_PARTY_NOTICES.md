# Third-party notices

The original Piper source, translations, icon and mouse artwork come from https://github.com/libratbag/piper at commit 5d3c8845b55643595ccb8029dfa5c7a2fb079e77. Original authorship and copyright notices remain in the files. See COPYING and README-upstream.md.

The retained upstream piper/ratbagd.py also carries its original Red Hat copyright and MIT-style permission notice; that notice remains intact.

The Qt frontend's Python/QML source uses SPDX-License-Identifier: GPL-2.0-or-later. Do not assume this overrides separately licensed artwork. In particular, data/svgs/logitech-g602.svg and data/svgs/logitech-g604.svg embed Creative Commons Attribution-ShareAlike 4.0 license metadata (https://creativecommons.org/licenses/by-sa/4.0/); retain their original attribution and metadata when redistributing or modifying them. All SVG files are supplied with their original metadata and internal symlinks.

Screenshots in docs/screenshots are actual captures of this application's mock-device UI. They display the bundled upstream artwork and system KDE/Breeze components; they contain no physical-device or personal data. Attribution for the depicted artwork is the same as for the corresponding bundled SVG. Screenshots are offered under GPL-2.0-or-later for original application content and CC-BY-SA-4.0 where applicable to depicted artwork; third-party marks retain their owners' rights.

Runtime dependencies such as PySide6/Qt, Kirigami, Breeze and dbus-next are not vendored. Their respective licenses and distribution packaging requirements apply separately.

The G600 encodable keyboard-code data in qt_piper/backend.py is derived from libratbag v0.18 src/libratbag-hidraw.c, commit 9f4789f8746188a75cd3090e94adf984f0ac4cc6 (https://github.com/libratbag/libratbag/blob/v0.18/src/libratbag-hidraw.c). Red Hat’s 2015 copyright and complete MIT permission notice are retained immediately above that derived table.
