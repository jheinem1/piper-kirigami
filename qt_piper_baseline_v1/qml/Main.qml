// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    objectName: "piperWindow"
    width: 1280; height: 840
    minimumWidth: 1024; minimumHeight: 680
    visible: true
    title: "Piper · Kirigami"
    property color surface: darkMode ? "#20252c" : "#eff0f1"
    property color altSurface: darkMode ? "#262c34" : "#e3e5e7"
    property color foreground: darkMode ? "#eff0f1" : "#232629"
    property bool darkMode: typeof startDark !== "undefined" && startDark
    Kirigami.Theme.inherit: false
    Kirigami.Theme.colorSet: Kirigami.Theme.Window
    Kirigami.Theme.backgroundColor: darkMode ? "#20252c" : "#eff0f1"
    Kirigami.Theme.alternateBackgroundColor: darkMode ? "#262c34" : "#e3e5e7"
    Kirigami.Theme.textColor: darkMode ? "#eff0f1" : "#232629"
    Kirigami.Theme.disabledTextColor: darkMode ? "#87919d" : "#7a8189"
    Kirigami.Theme.linkColor: darkMode ? "#70c8f4" : "#1478a8"
    palette.window: root.surface
    palette.windowText: root.foreground
    palette.base: darkMode ? "#171c22" : "#ffffff"
    palette.alternateBase: Kirigami.Theme.alternateBackgroundColor
    palette.text: root.foreground
    palette.button: darkMode ? "#343d48" : "#e9ecef"
    palette.buttonText: root.foreground
    palette.highlight: "#3daee9"
    palette.highlightedText: darkMode ? "#101820" : "#ffffff"
    palette.disabled.text: Kirigami.Theme.disabledTextColor
    palette.disabled.buttonText: Kirigami.Theme.disabledTextColor
    property bool discardOnClose: false
    onClosing: function(event) { if (backend.dirty && !discardOnClose) { event.accepted=false; closeDialog.open() } }
    property int page: 0
    property bool shifted: false
    property int selectedButton: -1
    property int selectedLed: -1
    property string hoverTarget: ""
    property var device: backend.selectedDevice
    property var profile: backend.selectedProfile
    property var buttons: profile.buttons || []
    property var leds: profile.leds || []
    property var resolutions: profile.resolutions || []
    property int diagramCount: page === 2 ? (leds.length || -1) : (buttons.length || -1)
    property var diagram: diagrams.describe(device.svg || "", page === 2 ? "leds" : "buttons", diagramCount, shifted)
    property string selectedTarget: page === 2 ? (selectedLed < 0 ? "" : "led" + selectedLed) : (selectedButton < 0 ? "" : "button" + (shifted ? selectedButton - 21 : selectedButton))
    function buttonAt(index) { for (let b of buttons) if (b.index === index) return b; return {} }
    function ledAt(index) { for (let l of leds) if (l.index === index) return l; return {} }
    function openButton(index) { selectedButton=index; mappingDialog.load(buttonAt(index)); mappingDialog.open() }
    function openLed(index) { selectedLed=index; ledDialog.load(ledAt(index)); ledDialog.open() }
    function chooseTarget(index) { if (page === 2) { if (ledAt(index).index !== undefined) openLed(index) } else if (buttonAt(index).index !== undefined) { page=1; openButton(index) } }
    Connections { target: backend; function onChanged() { if (root.selectedButton >= 0 && root.buttonAt(root.selectedButton).index === undefined) root.selectedButton=-1 } }

    pageStack.initialPage: Kirigami.Page {
        padding: 0
        background: Rectangle { color: root.surface }
        title: "Piper"
        globalToolBarStyle: Kirigami.ApplicationHeaderStyle.None
        ColumnLayout {
            anchors.fill: parent; spacing: 0
            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: 82
                color: root.altSurface
                RowLayout {
                    anchors.fill: parent; anchors.margins: 20; spacing: 16
                    Kirigami.Icon { source: "input-mouse"; Layout.preferredWidth: 36; Layout.preferredHeight: 36 }
                    ColumnLayout { spacing: 1
                        Kirigami.Heading { text: "Piper"; level: 1 }
                        Label { text: "Device configuration · Qt / Kirigami"; opacity: 0.66; font.pixelSize: 12 }
                    }
                    Item { Layout.fillWidth: true }
                    ToolButton { text: root.darkMode ? "Light theme" : "Dark theme"; objectName: "themeToggle"; onClicked: root.darkMode=!root.darkMode }
                    Label { text: backend.mock ? "DEMO DEVICE" : "RATBAGD"; font.bold: true; font.pixelSize: 11; color: Kirigami.Theme.linkColor }
                    ComboBox { id: deviceSelect; objectName: "deviceSelect"; Layout.preferredWidth: 270; model: backend.devices; textRole: "name"; currentIndex: backend.selectedDeviceIndex; onActivated: { backend.selectDevice(currentIndex); root.shifted=false } }
                    ToolButton { text: "↻"; objectName: "refreshButton"; enabled: !backend.dirty && !backend.busy; onClicked: backend.refresh(); ToolTip.text: "Refresh devices"; ToolTip.visible: hovered }
                }
            }
            Kirigami.InlineMessage {
                Layout.fillWidth: true; visible: backend.error !== ""; text: backend.error; type: Kirigami.MessageType.Error
                showCloseButton: true; onVisibleChanged: if (!visible && backend.error !== "") backend.clearError()
            }
            RowLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; spacing: 0
                Rectangle {
                    Layout.preferredWidth: 214; Layout.fillHeight: true; color: root.altSurface
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 16; spacing: 12
                        Label { text: "ON-DEVICE PROFILES"; font.pixelSize: 11; font.bold: true; opacity: 0.6 }
                        Repeater {
                            model: backend.profiles
                            delegate: Button {
                                required property var modelData
                                required property int index
                                Layout.fillWidth: true; Layout.preferredHeight: 48
                                text: (modelData.active ? "●  " : "○  ") + (modelData.name || "Profile " + (index+1))
                                checkable: true; checked: backend.selectedProfileIndex === index
                                objectName: "profile" + index
                                onClicked: backend.selectProfile(index)
                            }
                        }
                        Button { Layout.fillWidth: true; text: "Make active"; enabled: backend.connected && !profile.active; onClicked: backend.setProfileActive(); objectName: "activateProfile" }
                        TextField { id: profileName; Layout.fillWidth: true; text: profile.name || ""; placeholderText: "Profile name"; enabled: backend.connected && root.profile.canRename === true; onEditingFinished: if (text !== root.profile.name) backend.setProfileName(text); objectName: "profileName" }
                        CheckBox { text: "Profile enabled"; objectName: "profileEnabled"; checked: profile.enabled !== false; enabled: backend.connected && root.profile.canDisable === true; onClicked: backend.setProfileEnabled(checked) }
                        Item { Layout.fillHeight: true }
                        Kirigami.Separator { Layout.fillWidth: true }
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: backend.mock ? "Preview uses a simulated ratbagd device. No hardware is modified." : "Changes are staged until you press Apply."; opacity: 0.65; font.pixelSize: 11 }
                        RowLayout { visible: backend.mock
                            Button { text: backend.connected ? "Unplug" : "Reconnect"; onClicked: backend.connected ? backend.simulateDisconnect() : backend.simulateReconnect(); objectName: "simulateDisconnect" }
                            Button { objectName: "failCommitButton"; text: "Fail"; onClicked: backend.simulateCommitFailure(); ToolTip.text: "Fail the next simulated commit"; ToolTip.visible: hovered }
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true; Layout.fillHeight: true; spacing: 0
                    TabBar {
                        id: tabs; Layout.fillWidth: true; currentIndex: root.page; onCurrentIndexChanged: root.page=currentIndex
                        TabButton { text: "Sensitivity"; objectName: "sensitivityTab" }
                        TabButton { text: "Buttons"; objectName: "buttonsTab" }
                        TabButton { text: "Lighting"; objectName: "lightingTab" }
                        TabButton { text: "Advanced"; objectName: "advancedTab" }
                    }
                    StackLayout {
                        Layout.fillWidth: true; Layout.fillHeight: true; currentIndex: backend.connected && backend.devices.length > 0 ? 0 : 1
                        RowLayout {
                            spacing: 0
                            ColumnLayout {
                                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumWidth: 380; spacing: 8
                                RowLayout { Layout.fillWidth: true; Layout.margins: 20
                                    ColumnLayout { spacing: 3
                                        Kirigami.Heading { text: device.name || "Mouse"; level: 2 }
                                        Label { text: root.page === 2 ? "Select a light on the diagram" : "Select a button on the diagram"; opacity: 0.6; font.pixelSize: 12 }
                                    }
                                    Item { Layout.fillWidth: true }
                                }
                                RowLayout {
                                    Layout.alignment: Qt.AlignHCenter; visible: device.hasGShift === true && root.page !== 2
                                    Button { text: "Normal"; checkable: true; checked: !root.shifted; onClicked: { root.shifted=false; root.selectedButton=-1 } objectName: "normalLayer" }
                                    Button { text: "G-Shift"; checkable: true; checked: root.shifted; onClicked: { root.shifted=true; root.selectedButton=-1 } objectName: "gshiftLayer" }
                                }
                                Item {
                                    id: diagramArea; objectName: "diagramArea"; Layout.fillWidth: true; Layout.fillHeight: true; Layout.margins: 18
                                    property real scaleFactor: Math.min(Math.max(1,width-188) / Math.max(1,root.diagram.width), height / Math.max(1,root.diagram.height))
                                    Image {
                                        id: mouseImage; objectName: "mouseDiagram"
                                        anchors.centerIn: parent
                                        width: root.diagram.width * diagramArea.scaleFactor; height: root.diagram.height * diagramArea.scaleFactor
                                        source: root.diagram.source ? root.diagram.source + "&highlight=" + (root.hoverTarget || root.selectedTarget) : ""
                                        sourceSize.width: Math.ceil(width*2); sourceSize.height: Math.ceil(height*2)
                                        fillMode: Image.Stretch; smooth: true; cache: false
                                        MouseArea {
                                            anchors.fill: parent; hoverEnabled: true; cursorShape: root.hoverTarget ? Qt.PointingHandCursor : Qt.ArrowCursor
                                            onPositionChanged: function(mouse) { let h=diagrams.hitTarget(device.svg || "", root.page === 2 ? "leds" : "buttons", mouse.x / diagramArea.scaleFactor, mouse.y / diagramArea.scaleFactor, root.diagramCount, root.shifted); root.hoverTarget=h.id || "" }
                                            onExited: root.hoverTarget=""
                                            onClicked: function(mouse) { let h=diagrams.hitTarget(device.svg || "", root.page === 2 ? "leds" : "buttons", mouse.x / diagramArea.scaleFactor, mouse.y / diagramArea.scaleFactor, root.diagramCount, root.shifted); if (h.index !== undefined && h.index >= 0) root.chooseTarget(h.index) }
                                        }
                                        Repeater {
                                            model: root.diagram.hotspots || []
                                            delegate: ToolButton {
                                                required property var modelData
                                                objectName: "diagramTarget" + modelData.index
                                                width: 88; height: 27
                                                x: modelData.leaderX * diagramArea.scaleFactor + (modelData.side === "left" ? -width-5 : 5)
                                                y: Math.max(0, Math.min(mouseImage.height-height, modelData.leaderY * diagramArea.scaleFactor - height/2))
                                                visible: modelData.hasLeader
                                                text: root.page === 2 ? "LED "+(modelData.index+1) : (modelData.physicalIndex+1) + " · " + (root.buttonAt(modelData.index).actionLabel || "Disabled")
                                                contentItem: Text { text: parent.text; font: parent.font; color: root.foreground; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter }
                                                onHoveredChanged: root.hoverTarget=hovered ? modelData.id : ""
                                                font.pixelSize: 11
                                                highlighted: root.selectedTarget === modelData.id
                                                onClicked: root.chooseTarget(modelData.index)
                                                ToolTip.visible: hovered
                                                ToolTip.text: root.page === 2 ? "Configure LED " + (modelData.index+1) : (root.buttonAt(modelData.index).actionLabel || "Configure button " + (modelData.index+1))
                                            }
                                        }
                                    }
                                }
                                Label { Layout.alignment: Qt.AlignHCenter; Layout.bottomMargin: 18; text: root.hoverTarget ? "Click to configure " + root.hoverTarget : "Original Piper device artwork · interactive regions"; opacity: 0.55; font.pixelSize: 11 }
                            }
                            Kirigami.Separator { Layout.fillHeight: true }
                            ScrollView {
                                Layout.preferredWidth: 380; Layout.fillHeight: true; clip: true
                                ColumnLayout {
                                    width: 356; x: 12; spacing: 12
                                    Item { Layout.preferredHeight: 8 }
                                    Kirigami.Heading { text: root.page === 0 ? "Sensitivity" : root.page === 1 ? (root.shifted ? "G-Shift assignments" : "Button assignments") : root.page === 2 ? "Lighting zones" : "Advanced settings"; level: 2 }
                                    Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; opacity: 0.65; text: root.page === 0 ? "Adjust DPI stages and the polling rate for this profile." : root.page === 1 ? "Choose a mouse action, keyboard key, special action, or macro." : root.page === 2 ? "Configure each available LED independently." : "Options exposed by this device and profile." }
                                    ColumnLayout {
                                        visible: root.page === 0; Layout.fillWidth: true; spacing: 10
                                        Repeater {
                                            model: resolutions
                                            delegate: Frame {
                                                required property var modelData
                                                Layout.fillWidth: true
                                                ColumnLayout {
                                                    anchors.fill: parent
                                                    RowLayout {
                                                        Label { text: "Stage " + (modelData.index+1); font.bold: true }
                                                        Item { Layout.fillWidth: true }
                                                        RadioButton { text: "Active"; objectName: "resolutionActive"+modelData.index; checked: modelData.active; onClicked: backend.setResolutionActive(modelData.index) }
                                                    }
                                                    RowLayout {
                                                        ComboBox { id: dpiX; objectName: "dpiX"+modelData.index; model: modelData.values || []; currentIndex: model.indexOf(modelData.x); Layout.fillWidth: true; onActivated: backend.setDpi(modelData.index,Number(currentText),modelData.separateXY ? Number(dpiY.currentText) : Number(currentText)) }
                                                        Label { text: "DPI" }
                                                    }
                                                    RowLayout {
                                                        Label { text: "Y axis"; visible: modelData.separateXY === true }
                                                        ComboBox { id: dpiY; objectName: "dpiY"+modelData.index; visible: modelData.separateXY === true; model: modelData.values || []; currentIndex: model.indexOf(modelData.y); onActivated: backend.setDpi(modelData.index,Number(dpiX.currentText),Number(currentText)) }
                                                        CheckBox { text: "Enabled"; objectName: "resolutionEnabled"+modelData.index; checked: modelData.enabled !== false; enabled: modelData.canDisable === true; onClicked: backend.setResolutionEnabled(modelData.index,checked) }
                                                        RadioButton { text: "Default"; objectName: "resolutionDefault"+modelData.index; checked: modelData.default; onClicked: backend.setResolutionDefault(modelData.index) }
                                                    }
                                                }
                                            }
                                        }
                                        Label { text: "Polling rate"; font.bold: true }
                                        ComboBox { model: profile.reportRates || [125,250,500,1000]; currentIndex: model.indexOf(profile.reportRate); Layout.fillWidth: true; displayText: currentText + " Hz"; onActivated: backend.setReportRate(Number(currentText)); objectName: "reportRate" }
                                    }
                                    ColumnLayout {
                                        visible: root.page === 1; Layout.fillWidth: true; spacing: 5
                                        Repeater {
                                            model: buttons
                                            delegate: Button {
                                                required property var modelData
                                                visible: device.hasGShift !== true || (root.shifted ? modelData.index >= 21 : modelData.index < 20)
                                                Layout.fillWidth: true; Layout.preferredHeight: visible ? 44 : 0
                                                text: (modelData.label || "Button " + (modelData.index+1)) + "   ·   " + (modelData.actionLabel || "Disabled")
                                                onClicked: root.openButton(modelData.index)
                                                objectName: "buttonAssignment" + modelData.index
                                                highlighted: root.selectedButton === modelData.index
                                                onHoveredChanged: root.hoverTarget=hovered ? "button" + modelData.physicalIndex : ""
                                                ToolTip.visible: hovered; ToolTip.text: text
                                            }
                                        }
                                    }
                                    ColumnLayout {
                                        visible: root.page === 2; Layout.fillWidth: true
                                        Repeater {
                                            model: leds
                                            delegate: Button {
                                                required property var modelData
                                                Layout.fillWidth: true; Layout.preferredHeight: 60
                                                text: (modelData.name || "LED " + (modelData.index+1)) + "   ·   " + (modelData.modeLabel || modelData.mode)
                                                objectName: "ledAssignment" + modelData.index
                                                onClicked: root.openLed(modelData.index)
                                            }
                                        }
                                        Label { visible: leds.length === 0; text: "This device exposes no configurable LEDs."; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                    }
                                    ColumnLayout {
                                        visible: root.page === 3; Layout.fillWidth: true; spacing: 14
                                        CheckBox { text: "Angle snapping"; enabled: root.profile.angleSnapping !== undefined && root.profile.angleSnapping !== -1; checked: root.profile.angleSnapping === 1; onClicked: backend.setAngleSnapping(checked); objectName: "angleSnapping" }
                                        Label { text: "Debounce time"; font.bold: true }
                                        ComboBox { model: root.profile.debounces || []; enabled: count > 0; Layout.fillWidth: true; currentIndex: model.indexOf(root.profile.debounce); displayText: count ? currentText + " ms" : "Not supported"; onActivated: backend.setDebounce(Number(currentText)); objectName: "debounce" }
                                        Label { text: "Polling rate"; font.bold: true }
                                        ComboBox { model: root.profile.reportRates || []; enabled: count > 0; Layout.fillWidth: true; currentIndex: model.indexOf(root.profile.reportRate); displayText: count ? currentText + " Hz" : "Not supported"; onActivated: backend.setReportRate(Number(currentText)) }
                                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; opacity: 0.65; text: "Unavailable controls are not supported by this device’s ratbagd driver." }
                                    }
                                    Item { Layout.preferredHeight: 16 }
                                }
                            }
                        }
                        Kirigami.PlaceholderMessage {
                            icon.name: "input-mouse"; text: "No connected device"
                            explanation: "Connect a supported mouse and make sure ratbagd is running."
                            helpfulAction: Kirigami.Action { text: "Refresh"; onTriggered: backend.refresh() }
                        }
                    }
                }
            }
            Kirigami.Separator { Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true; Layout.margins: 16; spacing: 12
                Label { text: backend.busy ? "Communicating with ratbagd…" : backend.dirty ? "Unsaved changes" : (backend.status || "Ready"); color: backend.dirty ? (root.darkMode ? "#edb94d" : Kirigami.Theme.neutralTextColor) : root.foreground }
                Item { Layout.fillWidth: true }
                Button { text: "Reset"; enabled: backend.dirty && !backend.busy; onClicked: backend.reset(); objectName: "resetButton" }
                Button { text: "Apply"; highlighted: true; enabled: backend.connected && backend.dirty && !backend.busy; onClicked: backend.apply(); objectName: "applyButton" }
            }
        }
    }
    Dialog {
        id: closeDialog; objectName: "closeDialog"; title: "Unsaved changes"; modal: true; anchors.centerIn: parent; width: 400
        standardButtons: Dialog.NoButton
        contentItem: ColumnLayout {
            Label { text: "Close Piper and discard the changes you have not applied?"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            RowLayout { Item { Layout.fillWidth: true } Button { text: "Keep editing"; objectName: "keepEditingButton"; onClicked: closeDialog.close() } Button { text: "Discard and close"; objectName: "discardCloseButton"; onClicked: { root.discardOnClose=true; root.close() } } }
        }
    }
    MappingDialog { id: mappingDialog; backendObject: backend }
    LedDialog { id: ledDialog; backendObject: backend }
}
