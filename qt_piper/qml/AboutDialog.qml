// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Dialog {
    id: dialog
    objectName: "aboutDialog"
    title: "About Piper Kirigami"
    modal: true
    anchors.centerIn: parent
    width: Math.min(Kirigami.Units.gridUnit*34, parent.width-Kirigami.Units.largeSpacing*4)
    height: Math.min(Kirigami.Units.gridUnit*28, parent.height-Kirigami.Units.largeSpacing*4)
    standardButtons: Dialog.Close
    contentItem: ColumnLayout {
        spacing: Kirigami.Units.largeSpacing
        RowLayout {
            spacing: Kirigami.Units.largeSpacing
            Kirigami.Icon { source: Qt.resolvedUrl("../assets/piper.svg"); Layout.preferredWidth: Kirigami.Units.iconSizes.huge; Layout.preferredHeight: width }
            ColumnLayout {
                Kirigami.Heading { text: "Piper Kirigami"; level: 1 }
                Label { text: "Version " + (Qt.application.version || "Development") }
            }
            Item { Layout.fillWidth: true }
        }
        TabBar {
            id: tabs
            objectName: "aboutTabs"
            Layout.fillWidth: true
            TabButton { objectName: "aboutOverviewTab"; text: "About" }
            TabButton { objectName: "aboutComponentsTab"; text: "Components" }
            TabButton { objectName: "aboutAuthorsTab"; text: "Authors" }
        }
        Frame {
            Layout.fillWidth: true
            Layout.fillHeight: true
            ScrollView {
                id: contentScroll
                anchors.fill: parent
                clip: true
                contentWidth: availableWidth
                contentHeight: aboutStack.children[tabs.currentIndex].implicitHeight
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                StackLayout {
                    id: aboutStack
                    height: contentScroll.contentHeight
                    width: contentScroll.availableWidth
                    currentIndex: tabs.currentIndex
                    ColumnLayout {
                        spacing: Kirigami.Units.largeSpacing
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: "Configure gaming mice with Qt, KDE Kirigami and libratbag." }
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: "A Qt frontend maintained by James Heinemann, based on Piper by the libratbag developers." }
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; textFormat: Text.RichText; text: '<a href="https://www.gnu.org/licenses/old-licenses/gpl-2.0.html">License: GNU General Public License, version 2 or later</a>'; onLinkActivated: function(link) { Qt.openUrlExternally(link); } }
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; textFormat: Text.RichText; text: '<a href="https://github.com/jheinem1/piper-kirigami">Piper Kirigami project</a>'; onLinkActivated: function(link) { Qt.openUrlExternally(link); } }
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: "Active development. The project is not currently accepting issues or pull requests." }
                    }
                    ColumnLayout {
                        spacing: Kirigami.Units.largeSpacing
                        Repeater {
                            model: [
                                {name: "Qt " + desktopStyle.qtVersion + " / PySide6 " + desktopStyle.pysideVersion, description: "Application framework and Python bindings."},
                                {name: "KDE Kirigami", description: "Native KDE interface components."},
                                {name: "KDE QQC2 Desktop Style / Breeze", description: "Desktop controls, colors and icons."},
                                {name: "libratbag / ratbagd", description: "Mouse configuration through the system D-Bus service."},
                                {name: "dbus-next", description: "Python D-Bus client."}
                            ]
                            ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                Label { text: modelData.name; font.bold: true; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                Label { text: modelData.description; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                Kirigami.Separator { Layout.fillWidth: true }
                            }
                        }
                    }
                    ColumnLayout {
                        spacing: Kirigami.Units.largeSpacing
                        Label { text: "James Heinemann (jheinem1)"; font.bold: true; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        Label { text: "Piper Kirigami fork maintainer"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        Kirigami.Separator { Layout.fillWidth: true }
                        Label { text: "libratbag developers and Piper contributors"; font.bold: true; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        Label { text: "Original Piper application, device artwork and ratbagd integration."; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; textFormat: Text.RichText; text: '<a href="https://github.com/libratbag/piper/graphs/contributors">Upstream contributors</a>'; onLinkActivated: function(link) { Qt.openUrlExternally(link); } }
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: "Original copyright and artwork license notices are retained in the source distribution. This project is not endorsed by KDE or device vendors." }
                    }
                }
            }
        }
    }
}
