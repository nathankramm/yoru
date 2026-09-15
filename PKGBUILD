# Maintainer: Nathan Kramm <nathan.h.kramm@gmail.com>
pkgname=yoru
pkgver=1.0.1
pkgrel=1
pkgdesc="A pixel deer in the corner of your screen that teaches you Omarchy"
arch=('any')
url="https://github.com/nathankramm/yoru"
license=('MIT')
depends=('python' 'python-gobject' 'gtk4' 'gtk4-layer-shell' 'python-cairo' 'pango' 'glib2')
optdepends=('hyprland: focused-window context, live binding checks and the hide/show key')
install=yoru.install
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('dd2283e541a49fece8ff74006ba530ea1c44bf071403ac2893c23773056be53d')

# The binary only. Starting him at login and the Super + Ctrl + Y toggle are
# lines in the user's own ~/.config/hypr, which a package must not write;
# yoru.install prints them, and the README's by-hand section has them.
package() {
  cd "$pkgname-$pkgver"
  install -Dm755 yoru.py "$pkgdir/usr/bin/yoru"
  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
