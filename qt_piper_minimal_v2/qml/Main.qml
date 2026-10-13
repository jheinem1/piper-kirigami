// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    objectName: "piperWindow"
    width: 1200; height: 820; minimumWidth: 960; minimumHeight: 700
    visible: true; title: "Piper"
    SystemPalette { id: systemColors }
    property bool darkMode: (typeof startDark !== "undefined" && startDark) || systemColors.window.hslLightness < 0.5
    property color surface: darkMode ? "#20252b" : Qt.lighter(systemColors.window, 1.035)
    property color foreground: darkMode ? "#eef0f3" : systemColors.windowText
    property color subtle: darkMode ? "#a1a9b4" : "#6b7280"
    property color line: darkMode ? "#343b44" : "#dde1e6"
    property color accent: darkMode ? "#76c5ef" : "#167caf"
    palette.window: surface; palette.windowText: foreground; palette.text: foreground
    palette.base: darkMode ? "#1b2026" : "#ffffff"
    palette.button: darkMode ? "#323a45" : "#e9edf1"
    palette.buttonText: foreground; palette.highlight: accent
    palette.highlightedText: darkMode ? "#14202a" : "#ffffff"
    palette.disabled.text: subtle; palette.disabled.buttonText: subtle
    Kirigami.Theme.inherit: false
    Kirigami.Theme.textColor: foreground
    Kirigami.Theme.backgroundColor: surface
    property int page: 1
    property bool shifted: false
    property bool allAssignments: false
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
    property var bounds: diagram.deviceBounds || ({x:0,y:0,width:diagram.width,height:diagram.height})
    property var currentButton: buttonAt(selectedButton)
    property var currentLed: ledAt(selectedLed)
    property string selectedTarget: page === 2 ? (selectedLed < 0 ? "" : "led"+selectedLed) : (selectedButton < 0 ? "" : "button"+(shifted ? selectedButton-21 : selectedButton))
    property bool hasSelection: page === 2 ? selectedLed >= 0 : selectedButton >= 0
    property bool discardOnClose: false
    function buttonAt(index) { for (let b of buttons) if (b.index === index) return b; return {} }
    function ledAt(index) { for (let l of leds) if (l.index === index) return l; return {} }
    function openButton(index) { selectedButton=index; mappingDialog.load(buttonAt(index)); mappingDialog.open() }
    function openLed(index) { selectedLed=index; ledDialog.load(ledAt(index)); ledDialog.open() }
    function chooseTarget(index) { if (page===2) { if(ledAt(index).index!==undefined) selectedLed=index } else if(buttonAt(index).index!==undefined) { page=1; selectedButton=index }; allAssignments=false }
    function nextTarget(direction) {
        let list=root.diagram.hotspots||[];
        if (!list.length) return;
        let index=list.findIndex(function(h){ return h.index===(root.page===2?root.selectedLed:root.selectedButton) });
        index=(index+direction+list.length)%list.length;
        root.chooseTarget(list[index].index);
    }
    function clearSelection() { selectedButton=-1; selectedLed=-1; allAssignments=false }
    onClosing: function(event) { if(backend.dirty && !discardOnClose) { event.accepted=false; closeDialog.open() } }
    Shortcut { sequence: "Escape"; onActivated: root.clearSelection() }
    Shortcut { sequence: "Ctrl+Return"; onActivated: if(backend.dirty) backend.apply() }
    pageStack.initialPage: Kirigami.Page {
        padding: 0; title: "Piper"; globalToolBarStyle: Kirigami.ApplicationHeaderStyle.None
        background: Rectangle { color: root.surface }
        ColumnLayout {
            anchors.fill: parent; spacing: 0
            RowLayout {
                Layout.fillWidth: true; Layout.preferredHeight: 74; Layout.leftMargin: 34; Layout.rightMargin: 28; spacing: 16
                Label { text: "Piper"; font.pixelSize: 23; font.weight: Font.DemiBold; color: root.foreground }
                Item { Layout.fillWidth: true }
                ComboBox { id: deviceSelect; objectName: "deviceSelect"; Accessible.name: "Device"; model: backend.devices; textRole: "name"; currentIndex: backend.selectedDeviceIndex; Layout.preferredWidth: 258; onActivated: { backend.selectDevice(currentIndex); root.clearSelection(); root.shifted=false } }
                ComboBox { id: profileSelect; objectName: "profileSelect"; Accessible.name: "Profile"; model: backend.profiles; textRole: "name"; currentIndex: backend.selectedProfileIndex; Layout.preferredWidth: 140; onActivated: { backend.selectProfile(currentIndex); root.clearSelection() } }
                ToolButton { text: "⋯"; objectName: "appMenuButton"; font.pixelSize: 25; Accessible.name: "Application options"; onClicked: appMenu.open()
                    Menu { id: appMenu
                        MenuItem { text: root.darkMode ? "Light appearance" : "Dark appearance"; objectName: "themeToggle"; onTriggered: root.darkMode=!root.darkMode }
                        MenuItem { text: "Refresh devices"; enabled: !backend.dirty && !backend.busy; onTriggered: backend.refresh() }
                        MenuSeparator {}
                        MenuItem { text: "Advanced settings"; objectName: "advancedMenuItem"; onTriggered: root.page=3 }
                    }
                }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.line }
            RowLayout {
                Layout.fillWidth: true; Layout.preferredHeight: 64; Layout.leftMargin: 34; Layout.rightMargin: 34; spacing: 24
                Repeater {
                    model: [{label:"Buttons",value:1,name:"buttonsTab"},{label:"Sensitivity",value:0,name:"sensitivityTab"},{label:"Lighting",value:2,name:"lightingTab"},{label:"Profiles",value:4,name:"profileTab"}]
                    delegate: ToolButton {
                        required property var modelData
                        objectName: modelData.name; text: modelData.label
                        implicitHeight: 48; implicitWidth: labelText.implicitWidth+6
                        onClicked: { root.page=modelData.value; root.allAssignments=false }
                        contentItem: Label { id: labelText; text: parent.text; font.pixelSize: 14; font.weight: root.page===modelData.value ? Font.DemiBold : Font.Normal; color: root.page===modelData.value ? root.foreground : root.subtle; verticalAlignment: Text.AlignVCenter }
                        background: Item { Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 2; radius: 1; color: root.accent; visible: root.page===modelData.value } }
                    }
                }
                Item { Layout.fillWidth: true }
                Label { text: backend.mock ? "Preview device" : ""; color: root.subtle; font.pixelSize: 11 }
            }
            Kirigami.InlineMessage { Layout.fillWidth: true; text: backend.error; visible: backend.error!==""; type: Kirigami.MessageType.Error; showCloseButton: true }
            StackLayout {
                Layout.fillWidth: true; Layout.fillHeight: true
                currentIndex: !backend.connected || !backend.devices.length ? 3 : (root.page===1 || root.page===2) ? 0 : root.page===4 ? 2 : 1
                ColumnLayout {
                    spacing: 0
                    RowLayout {
                        Layout.fillWidth: true; Layout.leftMargin: 40; Layout.rightMargin: 40; Layout.topMargin: 18; spacing: 12
                        Label { text: root.page===2 ? "Lighting" : device.name || "Mouse"; font.pixelSize: 16; font.weight: Font.DemiBold; color: root.foreground }
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            visible: root.page===1 && device.hasGShift===true; implicitWidth: 184; implicitHeight: 36; radius: 8; color: root.darkMode ? "#181d23" : "#e5e9ee"
                            Row { anchors.fill: parent; anchors.margins: 3
                                Repeater {
                                    model: ["Normal","G-Shift"]
                                    delegate: Button {
                                        required property string modelData; required property int index
                                        objectName: index===0 ? "normalLayer" : "gshiftLayer"; width: 89; height: 30; text: modelData
                                        onClicked: { root.shifted=index===1; root.selectedButton=-1 }
                                        contentItem: Label { text: parent.text; color: root.foreground; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.pixelSize: 12; font.weight: root.shifted===(index===1) ? Font.DemiBold : Font.Normal }
                                        background: Rectangle { radius: 6; color: root.shifted===(index===1) ? (root.darkMode ? "#3c4653" : "#ffffff") : "transparent" }
                                    }
                                }
                            }
                        }
                        ToolButton { text: root.allAssignments ? "Close overview" : "All assignments"; objectName: "allAssignments"; checkable: true; checked: root.allAssignments; visible: root.page===1; onClicked: root.allAssignments=checked }
                    }
                    RowLayout {
                        Layout.fillWidth: true; Layout.fillHeight: true; spacing: 0
                        Item {
                            id: diagramArea; objectName: "diagramArea";
                            activeFocusOnTab: true
                            Accessible.role: Accessible.Button
                            Accessible.name: "Mouse diagram. Use arrow keys to select a button, and Enter to edit."
                            Keys.onRightPressed: root.nextTarget(1)
                            Keys.onLeftPressed: root.nextTarget(-1)
                            Keys.onDownPressed: root.nextTarget(1)
                            Keys.onUpPressed: root.nextTarget(-1)
                            Keys.onReturnPressed: if(root.hasSelection) root.page===2 ? root.openLed(root.selectedLed) : root.openButton(root.selectedButton)
                            Rectangle { anchors.fill: parent; anchors.margins: 2; color: "transparent"; border.color: root.accent; border.width: parent.activeFocus ? 1 : 0; radius: 8 }
                             Layout.fillWidth: true; Layout.fillHeight: true; Layout.margins: 32; clip: true
                            property real scaleFactor: Math.min((width-48)/Math.max(1,root.bounds.width),(height-70)/Math.max(1,root.bounds.height))
                            Image {
                                id: mouseImage; objectName: "mouseDiagram"
                                width: root.diagram.width*diagramArea.scaleFactor; height: root.diagram.height*diagramArea.scaleFactor
                                x: (diagramArea.width-root.bounds.width*diagramArea.scaleFactor)/2-root.bounds.x*diagramArea.scaleFactor
                                y: (diagramArea.height-root.bounds.height*diagramArea.scaleFactor)/2-root.bounds.y*diagramArea.scaleFactor-12
                                source: root.diagram.source ? root.diagram.source+"&leaders=0&highlight="+(root.hoverTarget||root.selectedTarget) : ""
                                sourceSize.width: Math.ceil(width*2); sourceSize.height: Math.ceil(height*2); fillMode: Image.Stretch; smooth: true; cache: false
                                MouseArea {
                                    anchors.fill: parent; hoverEnabled: true; cursorShape: root.hoverTarget ? Qt.PointingHandCursor : Qt.ArrowCursor
                                    onPositionChanged: function(mouse) { let h=diagrams.hitTarget(device.svg||"",root.page===2?"leds":"buttons",mouse.x/diagramArea.scaleFactor,mouse.y/diagramArea.scaleFactor,root.diagramCount,root.shifted); root.hoverTarget=h.id||"" }
                                    onExited: root.hoverTarget=""
                                    onClicked: function(mouse) { let h=diagrams.hitTarget(device.svg||"",root.page===2?"leds":"buttons",mouse.x/diagramArea.scaleFactor,mouse.y/diagramArea.scaleFactor,root.diagramCount,root.shifted); if(h.index!==undefined && h.index>=0) root.chooseTarget(h.index) }
                                }
                            }
                            Label { anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter; color: root.subtle; font.pixelSize: 12; text: root.page===2 ? "Select a lighting zone" : root.shifted ? "Select a button to configure its G-Shift action" : "Select a button to change its assignment" }
                        }
                        Rectangle { visible: root.hasSelection || root.allAssignments; width: 1; Layout.fillHeight: true; Layout.topMargin: 32; Layout.bottomMargin: 32; color: root.line }
                        ColumnLayout {
                            visible: root.hasSelection || root.allAssignments; Layout.preferredWidth: 306; Layout.minimumWidth: 306; Layout.maximumWidth: 306; Layout.fillHeight: true; Layout.margins: 32; spacing: 18
                            RowLayout { Layout.fillWidth: true
                                Label { text: root.allAssignments ? "Assignments" : root.page===2 ? "Lighting zone "+(root.selectedLed+1) : "Button "+((root.currentButton.physicalIndex||0)+1); font.pixelSize: 22; font.weight: Font.DemiBold; color: root.foreground }
                                Item { Layout.fillWidth: true }
                                ToolButton { text: "×"; objectName: "closeInspector"; Accessible.name: "Close inspector"; onClicked: root.clearSelection() }
                            }
                            ScrollView {
                                visible: root.allAssignments; Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                                ColumnLayout { width: 288; spacing: 2
                                    Repeater { model: root.buttons
                                        delegate: ItemDelegate {
                                            required property var modelData
                                            visible: !device.hasGShift || (root.shifted ? modelData.layer==="gshift" : modelData.layer==="normal")
                                            Layout.fillWidth: true; Layout.preferredHeight: visible ? 44 : 0
                                            objectName: "buttonAssignment"+modelData.index
                                            text: (modelData.physicalIndex+1)+"   "+modelData.actionLabel
                                            onClicked: root.chooseTarget(modelData.index)
                                            onHoveredChanged: root.hoverTarget=hovered?"button"+modelData.physicalIndex:""
                                        }
                                    }
                                }
                            }
                            ColumnLayout {
                                visible: !root.allAssignments; Layout.fillWidth: true; Layout.fillHeight: true; spacing: 18
                                Label { text: (root.shifted && root.page===1 ? "G-Shift  ·  " : "")+(profile.name||""); color: root.subtle; font.pixelSize: 12 }
                                Item { height: 10 }
                                Label { text: root.page===2 ? "LIGHTING EFFECT" : "CURRENT ASSIGNMENT"; font.pixelSize: 10; font.letterSpacing: 1; color: root.subtle }
                                Label { Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.WordWrap; text: root.page===2 ? ["Off","Solid","Cycle","Breathing"][root.currentLed.mode||0] : root.currentButton.actionLabel||"Disabled"; color: root.foreground; font.pixelSize: 23 }
                                Label { Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.WordWrap; text: root.page===2 ? "Choose a color and effect for this zone." : root.shifted ? "This action runs while G-Shift is held." : "This action runs when you press the button."; color: root.subtle; font.pixelSize: 13; lineHeight: 1.3 }
                                Button { text: root.page===2 ? "Edit lighting" : "Change assignment"; objectName: "chooseMapping"; Layout.fillWidth: true; onClicked: root.page===2 ? root.openLed(root.selectedLed) : root.openButton(root.selectedButton) }
                                Item { Layout.fillHeight: true }
                                Label { Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.WordWrap; text: "Changes stay in this profile until you apply them."; color: root.subtle; font.pixelSize: 11 }
                            }
                        }
                    }
                }
                ScrollView {
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    ColumnLayout {
                        width: Math.min(620, parent.width-80); x: Math.max(40,(parent.width-width)/2); spacing: 20
                        Item { height: 14 }
                        Kirigami.Heading { text: root.page===0 ? "Sensitivity" : "Advanced settings"; level: 1; color: root.foreground }
                        Label { text: profile.name||""; color: root.subtle }
                        ColumnLayout { visible: root.page===0; Layout.fillWidth: true
                                    ColumnLayout {
                                         Layout.fillWidth: true; spacing: 10
                                        Repeater {
                                            model: resolutions
                                            delegate: Item {
                                                required property var modelData
                                                Layout.fillWidth: true; implicitHeight: 140
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
                        }
                        ColumnLayout { visible: root.page===3; Layout.fillWidth: true
                                    ColumnLayout {
                                         Layout.fillWidth: true; spacing: 14
                                        CheckBox { text: "Angle snapping"; enabled: root.profile.angleSnapping !== undefined && root.profile.angleSnapping !== -1; checked: root.profile.angleSnapping === 1; onClicked: backend.setAngleSnapping(checked); objectName: "angleSnapping" }
                                        Label { text: "Debounce time"; font.bold: true }
                                        ComboBox { model: root.profile.debounces || []; enabled: count > 0; Layout.fillWidth: true; currentIndex: model.indexOf(root.profile.debounce); displayText: count ? currentText + " ms" : "Not supported"; onActivated: backend.setDebounce(Number(currentText)); objectName: "debounce" }
                                        Label { text: "Polling rate"; font.bold: true }
                                        ComboBox { model: root.profile.reportRates || []; enabled: count > 0; Layout.fillWidth: true; currentIndex: model.indexOf(root.profile.reportRate); displayText: count ? currentText + " Hz" : "Not supported"; onActivated: backend.setReportRate(Number(currentText)) }
                                        Label { Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.WordWrap; opacity: 0.65; text: "Unavailable controls are not supported by this device’s ratbagd driver." }
                                    }
                        }
                        ToolButton { visible: root.page===0; text: "Advanced settings →"; objectName: "advancedTab"; onClicked: root.page=3 }
                        Item { height: 30 }
                    }
                }
                Item {
                    ColumnLayout {
                        anchors.top: parent.top; anchors.topMargin: 32; anchors.horizontalCenter: parent.horizontalCenter; width: 540; spacing: 22
                        Kirigami.Heading { text: "On-device profiles"; level: 1; color: root.foreground }
                        Label { text: "Select a profile from the toolbar to edit its settings."; color: root.subtle }
                        Label { text: profile.name||""; font.pixelSize: 20; color: root.foreground }
                        TextField { text: profile.name||""; objectName: "profileName"; Layout.fillWidth: true; enabled: profile.canRename===true; onEditingFinished: if(text!==profile.name) backend.setProfileName(text) }
                        CheckBox { text: "Profile enabled"; objectName: "profileEnabled"; checked: profile.enabled!==false; enabled: profile.canDisable===true; onClicked: backend.setProfileEnabled(checked) }
                        Button { text: profile.active ? "Active profile" : "Make active"; objectName: "activateProfile"; enabled: !profile.active; onClicked: backend.setProfileActive() }
                        Label { text: "Profile names and availability depend on your device."; color: root.subtle; font.pixelSize: 12 }
                    }
                }
                Kirigami.PlaceholderMessage { text: "No connected device"; explanation: "Connect a supported mouse and make sure ratbagd is running."; helpfulAction: Kirigami.Action { text: "Refresh"; onTriggered: backend.refresh() } }
            }
            Rectangle { visible: backend.dirty || backend.busy; Layout.fillWidth: true; height: 1; color: root.line }
            RowLayout {
                visible: backend.dirty || backend.busy; Layout.fillWidth: true; Layout.leftMargin: 34; Layout.rightMargin: 34; Layout.topMargin: 12; Layout.bottomMargin: 12
                Label { text: backend.busy ? "Applying changes…" : "Unsaved changes"; color: root.foreground }
                Item { Layout.fillWidth: true }
                Button { text: "Discard"; objectName: "resetButton"; enabled: !backend.busy; onClicked: backend.reset() }
                Button { text: "Apply"; objectName: "applyButton"; highlighted: true; enabled: !backend.busy && backend.connected; onClicked: backend.apply() }
            }
        }
    }
    Dialog {
        id: closeDialog; objectName: "closeDialog"; title: "Unsaved changes"; modal: true; anchors.centerIn: parent; width: 400
        contentItem: ColumnLayout {
            Label { text: "Close Piper and discard the changes you have not applied?"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            RowLayout { Item { Layout.fillWidth: true } Button { text: "Keep editing"; objectName: "keepEditingButton"; onClicked: closeDialog.close() } Button { text: "Discard and close"; objectName: "discardCloseButton"; onClicked: { root.discardOnClose=true; root.close() } } }
        }
    }
    MappingDialog { id: mappingDialog; backendObject: backend }
    LedDialog { id: ledDialog; backendObject: backend }
}
