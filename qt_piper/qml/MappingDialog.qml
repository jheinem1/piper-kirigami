import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
Dialog {
    id: dialog
    objectName: "mappingDialog"
    property var backendObject
    onClosed: if (macroRecorder.active) macroRecorder.stop()
    Connections { target: macroRecorder; function onChanged() { if (!macroRecorder.active && macroRecorder.events.length) macroJson.text=JSON.stringify(macroRecorder.events) } }
    property int buttonIndex: -1
    property var mapping: ({})
    property string validation: ""
    onValidationChanged: if(validation!=="") Qt.callLater(dialog.revealValidation)
    property var types: ["none", "button", "key", "special", "macro"]
    property var typeLabels: ["Disabled", "Mouse button", "Keyboard key", "Special action", "Macro"]
    property var macroEvents: []
    property bool advancedMacro: false
    function macroPreview(text) {
        try {
            let events=JSON.parse(text); let names=[];
            for(let event of events) if(event[0]===1) {
                let name="Key "+event[1];
                for(let key of backendObject.keyChoices) if(key.value===event[1]) { name=key.label; break }
                names.push(name);
            }
            return names.length ? names.join(" + ") : "No keys recorded";
        } catch(e) { return "Edit sequence to correct this macro" }
    }
    function load(button) {
        mapping=button; buttonIndex=button.index; validation=""; advancedMacro=false; timedRecording.checked=false;
        types=["none","button","key","special","macro"].filter(function(t) { return (button.actionTypes || []).indexOf(t) >= 0 });
        let labels={none:"Disabled",button:"Mouse button",key:"Keyboard key",special:"Special action",macro:"Macro / key combination"};
        typeLabels=types.map(function(t) { return labels[t] });
        let t=types.indexOf(button.actionType); actionType.currentIndex=Math.max(0,t);
        mouseButton.value=button.actionType === "button" ? Number(button.actionValue) : 1;
        keyCode.value=button.actionType === "key" ? Number(button.actionValue) : 30;
        let ss=backendObject.specialActions || []; specialAction.currentIndex=0;
        for (let i=0;i<ss.length;i++) if (ss[i].value === button.actionValue) specialAction.currentIndex=i;
        macroEvents=button.actionType === "macro" ? JSON.parse(JSON.stringify(button.actionValue || [])) : [];
        macroJson.text=JSON.stringify(macroEvents);
    }
    function save() {
        let type=types[actionType.currentIndex]; let value=0;
        if(type === "button") value=mouseButton.value;
        else if(type === "key") value=keyCode.value;
        else if(type === "special") value=specialAction.currentValue;
        else if(type === "macro") {
            try { value=JSON.parse(macroJson.text); if(!Array.isArray(value)) throw "Expected an event list"; for(let e of value) if(!Array.isArray(e)||e.length!==2||![1,2,3].includes(e[0])||!Number.isInteger(e[1])||e[1]<0) throw "Each event must be [type, non-negative integer]"; }
            catch(e) { validation="Invalid macro: " + e; return }
        }
        if(backendObject.setButtonMapping(buttonIndex,type,value)) dialog.close();
        else validation=backendObject.error;
    }
    title: (mapping.layer === "gshift" ? "G-Shift · " : "") + (mapping.label || "Button " + (buttonIndex+1))
    modal: true; anchors.centerIn: parent
    width: Math.min(Kirigami.Units.gridUnit*31,parent.width-Kirigami.Units.largeSpacing*2)
    height: Math.min(implicitHeight,parent.height-Kirigami.Units.largeSpacing*2)
    padding: Kirigami.Units.largeSpacing*3
    onOpened: { mappingScroll.contentItem.contentY=0; actionType.forceActiveFocus(Qt.OtherFocusReason); }
    function revealFocusedControl() {
        if (!dialog.visible || !mappingScroll.Window.window) return;
        let focused=mappingScroll.Window.window.activeFocusItem;
        let flickable=mappingScroll.contentItem;
        if (!focused || !flickable || !flickable.contentItem) return;
        let ancestor=focused;
        while (ancestor && ancestor!==flickable.contentItem) ancestor=ancestor.parent;
        if (!ancestor) return;
        let top=focused.mapToItem(flickable.contentItem,0,0).y;
        let bottom=top+focused.height;
        if (top<flickable.contentY) flickable.contentY=Math.max(0,top);
        else if (bottom>flickable.contentY+flickable.height) flickable.contentY=Math.max(0,bottom-flickable.height);
    }
    function revealValidation() {
        if (!dialog.visible || dialog.validation==="") return;
        let flickable=mappingScroll.contentItem;
        if (flickable) flickable.contentY=Math.max(0,flickable.contentHeight-flickable.height);
    }
    Connections { target: mappingScroll.Window.window; function onActiveFocusItemChanged() { dialog.revealFocusedControl(); } }
    Connections {
        target: mappingScroll.contentItem
        function onContentHeightChanged() { if(dialog.validation!=="") Qt.callLater(dialog.revealValidation); }
        function onHeightChanged() { if(dialog.validation!=="") Qt.callLater(dialog.revealValidation); }
    }
    standardButtons: Dialog.NoButton
    contentItem: ScrollView {
        id: mappingScroll
        objectName: "mappingScroll"
        clip: true
        implicitHeight: mappingForm.implicitHeight
        contentWidth: availableWidth
        ColumnLayout {
        id: mappingForm
        width: mappingScroll.availableWidth
        spacing: Kirigami.Units.largeSpacing*2
        Label { text: "Assignment"; font.bold: true }
        NativeComboBox { id: actionType; objectName: "mappingType"; Accessible.name: "Assignment type"; model: dialog.typeLabels; Layout.fillWidth: true }
        RowLayout {
            visible: dialog.types[actionType.currentIndex] === "button"
            Label { text: "Mouse button number" }
            SpinBox { id: mouseButton; objectName: "mouseButtonNumber"; Accessible.name: "Mouse button number"; from: 1; to: 32; editable: true }
        }
        ColumnLayout {
            visible: dialog.types[actionType.currentIndex] === "key"; Layout.fillWidth: true
            NativeComboBox {
                id: keyPicker; objectName: "keyPicker"; Accessible.name: "Keyboard key"
                model: backendObject.keyChoices || []; textRole: "label"; valueRole: "value"
                Layout.fillWidth: true
                currentIndex: {
                    let choices=backendObject.keyChoices || [];
                    for (let index=0; index<choices.length; index++) if(choices[index].value===keyCode.value) return index;
                    return -1;
                }
                onActivated: keyCode.value=currentValue
            }
            RowLayout { Label { text: "Linux keycode" } SpinBox { id: keyCode; objectName: "keyCode"; Accessible.name: "Linux keycode"; from: 1; to: 767; editable: true } }
            Label { text: "For chords, choose Macro and add key press/release events."; opacity: 0.65; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        }
        NativeComboBox { id: specialAction; objectName: "specialAction"; Accessible.name: "Special action"; visible: dialog.types[actionType.currentIndex] === "special"; model: backendObject.specialActions || []; textRole: "label"; valueRole: "value"; Layout.fillWidth: true }
        ColumnLayout {
            visible: dialog.types[actionType.currentIndex] === "macro"; Layout.fillWidth: true; spacing: Kirigami.Units.largeSpacing
            Label { text: "Shortcut"; opacity: 0.65; font: Kirigami.Theme.smallFont }
            Kirigami.Heading { text: dialog.macroPreview(macroJson.text); level: 2; Layout.fillWidth: true; wrapMode: Text.WordWrap; topPadding: Kirigami.Units.largeSpacing; bottomPadding: Kirigami.Units.largeSpacing+Kirigami.Units.smallSpacing }
            RowLayout {
                Button { text: macroRecorder.active ? "Stop recording" : "Record shortcut"; objectName: "recordMacro"; onClicked: macroRecorder.active ? macroRecorder.stop() : macroRecorder.start(backendObject.selectedDevice.hasGShift !== true && timedRecording.checked) }
                CheckBox { id: timedRecording; text: "Include timing"; visible: backendObject.selectedDevice.hasGShift !== true }
            }
            Label { visible: macroRecorder.active; text: "Press your shortcut, then click Stop recording."; color: Kirigami.Theme.linkColor }
            ToolButton { text: dialog.advancedMacro ? "Hide advanced sequence" : "Advanced sequence"; objectName: "advancedMacroToggle"; onClicked: dialog.advancedMacro=!dialog.advancedMacro }
            Label { visible: dialog.advancedMacro; text: "Macro sequence"; font.bold: true }
            RowLayout {
                visible: dialog.advancedMacro
                NativeComboBox { id: eventType; objectName: "macroEventType"; Accessible.name: "Macro event type"; model: ["Key press", "Key release", "Wait (ms)"]; Layout.fillWidth: true }
                SpinBox { id: eventValue; objectName: "macroEventValue"; Accessible.name: eventType.currentIndex===2 ? "Delay in milliseconds" : "Macro event Linux keycode"; from: 0; to: 65535; value: 30; editable: true }
                Button { text: "Add"; Accessible.name: "Add macro event"; onClicked: { try { let ev=JSON.parse(macroJson.text); ev.push([eventType.currentIndex+1,eventValue.value]); macroJson.text=JSON.stringify(ev) } catch(e) { dialog.validation="Correct the JSON before adding an event." } } }
            }
            ScrollView { visible: dialog.advancedMacro; Layout.fillWidth: true; Layout.preferredHeight: Kirigami.Units.gridUnit*8
                TextArea { id: macroJson; objectName: "macroJson"; Accessible.name: "Macro sequence JSON"; text: "[]"; wrapMode: TextEdit.Wrap; font.family: "monospace" }
            }
            Label { visible: dialog.advancedMacro; text: "Each event is [type, value]. Types: 1 = press, 2 = release, 3 = delay in milliseconds. Keys use Linux evdev codes. Example Ctrl+C: [[1,29],[1,46],[2,46],[2,29]]."; wrapMode: Text.WordWrap; Layout.fillWidth: true; opacity: 0.65; font: Kirigami.Theme.smallFont }
            RowLayout { visible: dialog.advancedMacro; Button { text: "Clear"; Accessible.name: "Clear macro sequence"; onClicked: macroJson.text="[]" } Button { text: "Insert Ctrl+C"; onClicked: macroJson.text="[[1,29],[1,46],[2,46],[2,29]]" } }
        }
        Kirigami.InlineMessage { objectName: "mappingValidation"; text: dialog.validation; visible: dialog.validation !== ""; type: Kirigami.MessageType.Error; Layout.fillWidth: true }
        }
    }
    footer: DialogButtonBox {
        Button { text: "Cancel"; objectName: "mappingCancel"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
        Button { text: "Save assignment"; objectName: "mappingSave"; highlighted: true; DialogButtonBox.buttonRole: DialogButtonBox.ApplyRole; onClicked: dialog.save() }
        onRejected: dialog.close()
    }
}
