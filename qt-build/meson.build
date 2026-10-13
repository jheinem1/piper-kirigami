project('piper-kirigami', version: '0.1.0', license: 'GPL-2.0-or-later', meson_version: '>=0.61')
python = import('python').find_installation('python3')
pkgdir = get_option('prefix') / get_option('datadir') / 'piper-kirigami'
install_subdir('../qt_piper', install_dir: pkgdir, exclude_directories: ['__pycache__', '.ruff_cache', '.pytest_cache'], exclude_files: ['ruff.toml'])
install_subdir('../data/svgs', install_dir: pkgdir / 'data')
install_data('../COPYING', install_dir: pkgdir)
configuration = configuration_data()
configuration.set('python', python.full_path())
configuration.set('pkgdir', pkgdir)
configure_file(input: 'piper-kirigami.in', output: 'piper-kirigami', configuration: configuration,
  install: true, install_dir: get_option('bindir'), install_mode: 'rwxr-xr-x')
install_data('org.freedesktop.Piper.Kirigami.desktop', install_dir: get_option('datadir') / 'applications')
install_data('../data/org.freedesktop.Piper.svg', install_dir: get_option('datadir') / 'icons/hicolor/scalable/apps', rename: 'org.freedesktop.Piper.Kirigami.svg')
summary({'Python': python.full_path(), 'Resources': pkgdir, 'Runtime': 'PySide6, Qt Quick Controls 2, KDE Kirigami, dbus-next, ratbagd API 2'}, section: 'Piper Kirigami')
