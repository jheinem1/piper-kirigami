// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtCore
import org.kde.kirigami as Kirigami

ScrollView {
    id: page
    objectName: "profilesScroll"
    property var backendObject
    readonly property var profile: backendObject.selectedProfile
    readonly property var device: backendObject.selectedDevice
    property string shownProfilePath: ""
    property var saveContext: ({})
    property var loadContext: ({})
    property var filePreview: ({})
    property string fileMessage: ""
    signal selectSlot(int index)
    Accessible.role: Accessible.Pane
    Accessible.name: "On-device profiles"
    clip: true
    contentWidth: availableWidth
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

    function refreshSlot() {
        if(shownProfilePath===(profile.path || "")) return;
        shownProfilePath=profile.path || "";
        fileName.text=backendObject.profileFileName || (device.name || "Mouse")+" - Slot "+(Number(profile.index || 0)+1);
        fileMessage="";
        if(filePreview.token) backendObject.cancelProfileImport(filePreview.token);
        filePreview=({});
        importReview.close();
    }
    function previewFile(url) {
        fileMessage="";
        filePreview=backendObject.inspectProfileFile(url,loadContext);
        if(filePreview.token) importReview.open();
        return filePreview.token!==undefined;
    }
    Connections { target: page.backendObject; function onChanged() { page.refreshSlot(); } }
    Component.onCompleted: refreshSlot()
    onVisibleChanged: if(!visible) {
        if(filePreview.token) backendObject.cancelProfileImport(filePreview.token);
        filePreview=({}); importReview.close();
    }

    FileDialog {
        id: saveDialog
        objectName: "saveProfileFileDialog"
        title: "Save profile to JSON"
        fileMode: FileDialog.SaveFile
        nameFilters: ["Piper profiles (*.json)"]
        defaultSuffix: "json"
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: {
            // SaveFile's native dialog owns replacement confirmation.
            if(page.backendObject.exportProfileFile(selectedFile.toString(),fileName.text,page.saveContext,true))
                page.fileMessage="Saved the current settings, including pending edits, to a JSON file.";
        }
    }
    FileDialog {
        id: loadDialog
        objectName: "loadProfileFileDialog"
        title: "Load profile from JSON"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Piper profiles (*.json)", "All files (*)"]
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: page.previewFile(selectedFile.toString())
    }
    Dialog {
        id: importReview
        objectName: "profileImportReview"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(parent ? parent.width-Kirigami.Units.largeSpacing*4 : 460, Kirigami.Units.gridUnit*30)
        title: "Load into slot "+(page.filePreview.slot || "")+"?"
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape
        standardButtons: Dialog.Ok | Dialog.Cancel
        onOpened: {
            standardButton(Dialog.Ok).text="Load as pending changes";
            standardButton(Dialog.Cancel).forceActiveFocus(Qt.OtherFocusReason);
        }
        onAccepted: {
            if(page.backendObject.importProfileFile(page.filePreview.token || "")) {
                fileName.text=page.filePreview.name;
                page.fileMessage="Loaded “"+page.filePreview.name+"” as pending changes. Review the settings, then Apply to write them to the mouse.";
            }
            page.filePreview=({});
        }
        onRejected: {
            page.backendObject.cancelProfileImport(page.filePreview.token || "");
            page.filePreview=({});
        }
        contentItem: ColumnLayout {
            spacing: Kirigami.Units.largeSpacing
            Label {
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: "“"+(page.filePreview.name || "")+"” replaces this slot’s settings in the local draft, including any pending edits to those settings."
            }
            Label {
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: (page.filePreview.dpiStages || 0)+" DPI stages · "+(page.filePreview.buttons || 0)+" assignments"+(page.filePreview.gshiftButtons ? " (including "+page.filePreview.gshiftButtons+" G-Shift)" : "")+" · "+(page.filePreview.leds || 0)+" lighting zones"
            }
            Label {
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: "The slot’s name, enabled state and active state stay unchanged. Nothing is written to the mouse until you choose Apply."
            }
        }
    }

    ColumnLayout {
        width: Math.max(0,Math.min(Kirigami.Units.gridUnit*42,page.availableWidth-Kirigami.Units.largeSpacing*4))
        x: (page.availableWidth-width)/2
        spacing: Kirigami.Units.largeSpacing*2
        Item { Layout.preferredHeight: Kirigami.Units.largeSpacing }
        Kirigami.Heading { level: 2; text: "On-device slots" }
        Frame {
            Layout.fillWidth: true
            padding: 0
            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                Repeater {
                    model: page.backendObject.profiles
                    RadioDelegate {
                        required property var modelData
                        required property int index
                        objectName: "profileSlot"+modelData.index
                        Layout.fillWidth: true
                        checked: index===page.backendObject.selectedProfileIndex
                        enabled: page.backendObject.connected && !page.backendObject.busy
                        text: "Slot "+(modelData.index+1)+(modelData.rawName ? " · "+modelData.rawName : "")+(modelData.active ? " · Active" : "")+(modelData.enabled ? "" : " · Disabled")
                        Accessible.name: text
                        onClicked: page.selectSlot(index)
                    }
                }
            }
        }
        Kirigami.FormLayout {
            Layout.fillWidth: true
            RowLayout {
                Kirigami.FormData.label: "Slot name:"
                TextField {
                    id: slotName
                    objectName: "profileName"
                    text: page.profile.name || ""
                    Accessible.name: "Profile name"
                    Layout.preferredWidth: Kirigami.Units.gridUnit*18
                    Layout.maximumWidth: Kirigami.Units.gridUnit*18
                    Layout.fillWidth: true
                    enabled: page.profile.canRename===true && !page.backendObject.busy
                    onEditingFinished: if(text!==page.profile.name) page.backendObject.setProfileName(text)
                }
                ContextHelpButton {
                    objectName: "profileNameInfo"
                    helpText: page.profile.canRename ? "This name is stored in the mouse. The JSON file has its own name." : "This mouse does not support renaming its on-device slots. You can give saved JSON profiles any name."
                }
            }
            RowLayout {
                Kirigami.FormData.label: "Slot:"
                CheckBox {
                    objectName: "profileEnabled"
                    text: "Enabled"
                    Accessible.name: "Enable selected profile"
                    checked: page.profile.enabled!==false
                    enabled: page.profile.canDisable===true && !page.backendObject.busy
                    onClicked: page.backendObject.setProfileEnabled(checked)
                }
                ContextHelpButton {
                    objectName: "profileEnabledInfo"
                    helpText: page.profile.canDisable ? "The active slot cannot be disabled. Make another enabled slot active first." : "This mouse keeps all of its on-device slots enabled."
                }
            }
            RowLayout {
                Kirigami.FormData.label: "Status:"
                Label { text: page.profile.active ? "Active profile" : "Inactive profile" }
                Button {
                    objectName: "activateProfile"
                    text: "Make active"
                    visible: !page.profile.active
                    enabled: page.profile.active===false && page.profile.enabled!==false && !page.backendObject.busy
                    onClicked: page.backendObject.setProfileActive()
                }
            }
        }
        Kirigami.Separator { Layout.fillWidth: true }
        RowLayout {
            Kirigami.Heading { level: 2; text: "Profile files" }
            ContextHelpButton {
                objectName: "profileFileInfo"
                helpText: "JSON files contain DPI, polling rate, button assignments (both layers on G600), lighting and supported advanced settings. Saving includes pending edits. Loading replaces those settings in the selected slot’s draft, never its name or active state. Profiles Apply and Reset include the loaded settings, but do not change other slots."
            }
        }
        Kirigami.FormLayout {
            Layout.fillWidth: true
            TextField {
                id: fileName
                objectName: "profileFileName"
                Kirigami.FormData.label: "File profile name:"
                Accessible.name: "Profile file name"
                Layout.fillWidth: true
                Layout.preferredWidth: Kirigami.Units.gridUnit*18
                Layout.maximumWidth: Kirigami.Units.gridUnit*18
                maximumLength: 255
                enabled: !page.backendObject.busy
            }
            RowLayout {
                spacing: Kirigami.Units.smallSpacing
                Button {
                    objectName: "exportProfileFile"
                    text: "Save to File…"
                    icon.name: "document-save-as"
                    enabled: page.backendObject.connected && !page.backendObject.busy && fileName.text.trim().length>0
                    onClicked: {
                        page.saveContext=page.backendObject.capturePageContext("profiles");
                        if(!page.saveContext.token) return;
                        let stem=fileName.text.trim().replace(/[\\/:*?"<>|]/g,"_");
                        saveDialog.currentFile=saveDialog.currentFolder+"/"+encodeURIComponent(stem)+".json";
                        saveDialog.open();
                    }
                }
                Button {
                    objectName: "importProfileFile"
                    text: "Load from File…"
                    icon.name: "document-open"
                    enabled: page.backendObject.connected && !page.backendObject.busy
                    onClicked: {
                        page.loadContext=page.backendObject.capturePageContext("profiles");
                        if(page.loadContext.token) loadDialog.open();
                    }
                }
            }
        }
        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: page.fileMessage!==""
            type: Kirigami.MessageType.Information
            text: page.fileMessage
        }
        Label {
            Layout.fillWidth: true
            visible: page.backendObject.profileImportPending
            wrapMode: Text.Wrap
            text: "Loaded settings are pending for this slot. Apply writes them to the mouse; Reset discards them."
        }
        Item { Layout.preferredHeight: Kirigami.Units.largeSpacing*2 }
    }
}
