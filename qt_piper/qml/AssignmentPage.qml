import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
Pane {
    id: dialog
    objectName: "assignmentPage"
    property bool loading: false
    property var mappingContext: ({})
    property bool contextValid: false
    property bool backendDirty: false
    property bool applying: false
    property string initialFingerprint: ""
    property string applyError: ""
    property string recordingError: ""
    signal applied(bool success)
    readonly property var payload: {
        let type=types[actionType.currentIndex] || "none";
        let value=0;
        if(type==="button") value=mouseButton.value;
        else if(type==="key") value=keyCode.value;
        else if(type==="special") value=specialAction.currentValue;
        else if(type==="macro") {
            try {
                value=JSON.parse(macroJson.text);
                if(!Array.isArray(value)) throw "Expected an event list";
                for(let event of value) if(!Array.isArray(event) || event.length!==2 || ![1,2,3].includes(event[0]) || !Number.isInteger(event[1]) || event[1]<0) throw "Each event must be [type, non-negative integer]";
            } catch(error) { return {type:type, value:null, error:"Invalid macro: "+error}; }
        }
        return {type:type,value:value,error:""};
    }
    readonly property string draftFingerprint: JSON.stringify([payload.type,payload.type==="macro" ? macroJson.text : payload.value])
    readonly property bool localDirty: !loading && draftFingerprint!==initialFingerprint
    readonly property bool edited: localDirty || backendDirty
    readonly property string mappingValidationError: payload.error || (!loading && contextValid ? backendObject.validateMapping(mappingContext,payload.type,payload.value) : "")
    readonly property bool valid: contextValid && mappingValidationError===""
    readonly property bool canApply: edited && contextValid && mappingValidationError==="" && recordingError==="" && !applying && !backendObject.busy && !macroRecorder.active
    readonly property string helpTopic: "assignment-"+(payload.type || "overview")
    onDraftFingerprintChanged: if(!loading) { applyError=""; recordingError=""; }
    function refreshContext() {
        contextValid=buttonIndex>=0 && backendObject.mappingContextValid(mappingContext);
        backendDirty=contextValid && backendObject.mappingDirty(mappingContext);
    }
    Connections {
        target: backendObject
        function onChanged() { dialog.refreshContext(); if(valuePicker.visible && !dialog.contextValid) valuePicker.close(); }
        function onMappingApplyFinished(token,success,message) {
            if(token!==dialog.mappingContext.token) return;
            dialog.applying=false;
            if(success) {
                let updated=backendObject.mappingForContext(dialog.mappingContext);
                if(updated.index!==undefined) dialog.load(updated,dialog.mappingContext);
            } else dialog.applyError=message || backendObject.error || "The assignment could not be applied.";
            dialog.applied(success);
        }
    }
    function applyDraft() {
        if(!canApply) return false;
        applyError=""; applying=true;
        if(!backendObject.applyMapping(mappingContext,payload.type,payload.value)) {
            applying=false; applyError=backendObject.error || "The assignment could not be applied.";
            return false;
        }
        return true;
    }
    function resetDraft() {
        cancelRecording();
        let restored=backendObject.resetMapping(mappingContext);
        if(restored.index===undefined) { applyError=backendObject.error; return false; }
        load(restored,mappingContext);
        return true;
    }
    function discardDraft() {
        if(contextValid) return resetDraft();
        cancelRecording();
        initialFingerprint=draftFingerprint; backendDirty=false; applyError="";
        return true;
    }
    property string title: (mapping.layer === "gshift" ? "G-Shift · " : "") + (mapping.label || "Button " + (buttonIndex+1))
    function cancelRecording() {
        if(chordCaptureActive) macroRecorder.cancel();
        chordCaptureActive=false;
    }
    function focusFirst() { actionType.forceActiveFocus(Qt.OtherFocusReason); }
    property var backendObject
    onVisibleChanged: if(!visible) cancelRecording()
    Connections {
        target: macroRecorder
        function onCancelled() { dialog.chordCaptureActive=false; }
        function onChanged() {
            if(!dialog.visible) return;
            if(macroRecorder.active) dialog.recordingError=macroRecorder.error;
            else if(dialog.chordCaptureActive) {
                dialog.chordCaptureActive=false;
                if(macroRecorder.error) dialog.recordingError=macroRecorder.error;
                else if(macroRecorder.events.length) macroJson.text=JSON.stringify(macroRecorder.events);
            }
        }
    }
    property int buttonIndex: -1
    property var mapping: ({})
    readonly property string validation: recordingError || mappingValidationError || applyError || (buttonIndex>=0 && !contextValid ? "This assignment is no longer available. Go back and reopen it." : "")
    onValidationChanged: if(validation!=="") Qt.callLater(dialog.revealValidation)
    property var types: ["none", "button", "key", "special", "macro"]
    property var typeLabels: ["Disabled", "Mouse button", "Keyboard key", "Special action", "Macro"]
    property var macroEvents: []
    property bool chordCaptureActive: false
    readonly property bool chordOnly: backendObject.selectedDevice.hasGShift===true
    readonly property var visualEvents: {
        try { let events=JSON.parse(macroJson.text); return Array.isArray(events) ? events : []; }
        catch(error) { return []; }
    }
    readonly property var eventKeyChoices: contextValid ? backendObject.mappingKeyChoices(mappingContext).filter(function(choice){return choice.selectable!==false;}) : []
    readonly property var mouseButtonChoices: Array.from({length:chordOnly ? 5 : 32},function(_,index){return {value:index+1,label:"Mouse button "+(index+1)};})
    function keyLabel(value) {
        if(value===0) return "Reserved modifier placeholder";
        for(let choice of eventKeyChoices) if(choice.value===value) return choice.label;
        return "Key "+value;
    }
    function openValuePicker(control,title,choices,value,callback) {
        cancelRecording();
        valuePicker.eventMode=false; valuePicker.title=title; valuePicker.choices=choices;
        valuePicker.selectedValue=value; valuePicker.opener=control;
        valuePicker.contextToken=mappingContext.token;
        valuePicker.acceptValue=callback;
        valuePicker.open();
    }
    ValuePicker {
        id:valuePicker
        hostItem:dialog.Window.window ? dialog.Window.window.contentItem : null
        contextCheck:function(token){return dialog.visible && dialog.contextValid && dialog.mappingContext.token===token;}
    }
    SpinBox { id:mouseButton; objectName:"mouseButtonNumber"; visible:false; from:1;to:32;value:1 }
    SpinBox { id:keyCode; objectName:"keyCode"; visible:false; from:1;to:767;value:30 }
    function writeEvents(events) { macroJson.text=JSON.stringify(events); }
    function updateEvent(index,kind,value) {
        let events=JSON.parse(JSON.stringify(visualEvents));
        if(index<0 || index>=events.length) return;
        events[index]=[kind,value]; writeEvents(events);
    }
    function removeEvent(index) {
        let events=JSON.parse(JSON.stringify(visualEvents)); events.splice(index,1); writeEvents(events); Qt.callLater(dialog.focusAddEvent);
    }
    function moveEvent(index,offset) {
        let events=JSON.parse(JSON.stringify(visualEvents)); let target=index+offset;
        if(target<0 || target>=events.length) return;
        let event=events.splice(index,1)[0]; events.splice(target,0,event); writeEvents(events);
        eventList.currentIndex=target; eventList.positionViewAtIndex(target,ListView.Contain);
        Qt.callLater(function() {
            let row=eventList.itemAtIndex(target);
            if(!row) return;
            let control=offset<0 ? row.moveUpControl : row.moveDownControl;
            (control.enabled ? control : row).forceActiveFocus(Qt.OtherFocusReason);
        });
    }
    function addEventControl() {
        function find(item) {
            if(item.action && item.action.objectName==="macroAddEvent") return item;
            for(let child of (item.children || [])) {let found=find(child);if(found) return found;}
            return null;
        }
        return find(eventHeader);
    }
    function focusAddEvent() { let control=addEventControl(); if(control) control.forceActiveFocus(Qt.OtherFocusReason); }
    function openAddEvent() {
        cancelRecording();
        valuePicker.title="Add macro event"; valuePicker.choices=eventKeyChoices;
        valuePicker.selectedValue=-1; valuePicker.opener=addEventControl();
        valuePicker.contextToken=mappingContext.token;
        valuePicker.eventMode=true; valuePicker.eventKind=1; valuePicker.allowDelay=!chordOnly;
        valuePicker.acceptValue=function(value,kind) {
            let events=JSON.parse(JSON.stringify(dialog.visualEvents));
            events.push([kind,value]); dialog.writeEvents(events);
            eventList.currentIndex=events.length-1; eventList.positionViewAtEnd();
        };
        valuePicker.open();
    }
    TextEdit { id: macroJson; objectName:"macroJson"; visible:false; text:"[]" }
    function macroPreview(text) {
        try {
            let events=JSON.parse(text); let names=[];
            for(let event of events) if(event[0]===1 && event[1]!==0) {
                let name="Key "+event[1];
                for(let key of backendObject.keyChoices) if(key.value===event[1]) { name=key.label; break }
                names.push(name);
            }
            return names.length ? names.join(" + ") : "No keys recorded";
        } catch(e) { return "Edit sequence to correct this macro" }
    }
    function load(button, capturedContext) {
        loading=true; mapping=button; buttonIndex=button.index; mappingContext=capturedContext || backendObject.captureMappingContext(button.index); applyError=""; recordingError=""; 
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
        initialFingerprint=draftFingerprint; loading=false; refreshContext(); mappingScroll.contentItem.contentY=0;
    }
    enabled: !applying
    padding: 0
    function revealFocusedControl() {
        if (!dialog.visible || !mappingScroll.Window.window) return;
        let focused=mappingScroll.Window.window.activeFocusItem;
        let flickable=mappingScroll.contentItem;
        if (!focused || !flickable || !flickable.contentItem) return;
        let ancestor=focused;
        while (ancestor && ancestor!==flickable.contentItem) {
            // Event rows have their own bounded list and focus-reveal handling.
            if (ancestor===eventList) return;
            ancestor=ancestor.parent;
        }
        if (!ancestor) return;
        let top=focused.mapToItem(flickable.contentItem,0,0).y;
        let bottom=top+focused.height;
        let maximumY=Math.max(0,flickable.contentHeight-flickable.height);
        if (top<flickable.contentY) flickable.contentY=Math.min(maximumY,Math.max(0,top));
        else if (bottom>flickable.contentY+flickable.height) flickable.contentY=Math.min(maximumY,Math.max(0,bottom-flickable.height));
    }
    function revealValidation() {
        if (!dialog.visible || dialog.validation==="") return;
        let flickable=mappingScroll.contentItem;
        if (flickable) flickable.contentY=Math.max(0,flickable.contentHeight-flickable.height);
    }
    Connections {
        target: mappingScroll.Window.window
        function onActiveFocusItemChanged() { dialog.revealFocusedControl(); }
        function onActiveChanged() { if(!mappingScroll.Window.window.active) dialog.cancelRecording(); }
    }
    Connections {
        target: mappingScroll.contentItem
        function onContentHeightChanged() { if(dialog.validation!=="") Qt.callLater(dialog.revealValidation); }
        function onHeightChanged() { if(dialog.validation!=="") Qt.callLater(dialog.revealValidation); }
    }
    contentItem: ScrollView {
        id: mappingScroll
        objectName: "mappingScroll"
        clip: true
        contentWidth: availableWidth
        ColumnLayout {
            objectName:"assignmentPageLayout"
            width:mappingScroll.availableWidth
            height:Math.max(implicitHeight,mappingScroll.availableHeight)
            spacing:Kirigami.Units.largeSpacing
        Kirigami.FormLayout {
            id: mappingForm
            objectName: "assignmentForm"
            Layout.preferredWidth:Math.min(mappingScroll.availableWidth,Kirigami.Units.gridUnit*46)
            Layout.alignment:Qt.AlignHCenter | Qt.AlignTop
            Layout.fillHeight:false
            Layout.topMargin:Kirigami.Units.largeSpacing*3
            FontMetrics { id: formLabelMetrics; font: Kirigami.Theme.defaultFont }
            wideMode: width>=controlWidth+Math.max(formLabelMetrics.advanceWidth("Linux keycode:"),formLabelMetrics.advanceWidth("Assignment:"))+Kirigami.Units.largeSpacing*2
            readonly property real compactControlWidth: Math.min(controlWidth,Kirigami.Units.gridUnit*18)
            readonly property real controlWidth: Math.min(Kirigami.Units.gridUnit*32,Math.max(Kirigami.Units.gridUnit*12,width-Kirigami.Units.gridUnit*10))
            Item {
                Layout.maximumWidth: visible ? Number.POSITIVE_INFINITY : 0
                Kirigami.FormData.label:"Assignment:"
                Kirigami.FormData.buddyFor:actionType
                Layout.preferredWidth:Math.min(actionType.implicitWidth+Kirigami.Units.gridUnit*2,Kirigami.Units.gridUnit*18)
                implicitWidth:actionType.implicitWidth
                implicitHeight:actionType.implicitHeight+Kirigami.Units.smallSpacing*2
                ComboBox {
                    id:actionType; objectName:"mappingType"
                    width:parent.width; y:Kirigami.Units.smallSpacing
                    Accessible.name:"Assignment type"
                    model:dialog.typeLabels
                }
            }
            Item {
                Layout.maximumWidth: visible ? Number.POSITIVE_INFINITY : 0
                visible: dialog.types[actionType.currentIndex]==="button"
                Kirigami.FormData.label: "Mouse button:"
                Kirigami.FormData.buddyFor: mouseButtonPicker
                implicitWidth: mouseButtonPicker.implicitWidth
                implicitHeight: mouseButtonPicker.implicitHeight+Kirigami.Units.smallSpacing*2
                Button {
                    id:mouseButtonPicker; objectName:"mouseButtonPicker"
                    width:parent.width; y:Kirigami.Units.smallSpacing
                    readonly property int currentValue:mouseButton.value
                    text:"Mouse button "+currentValue; icon.name:"input-mouse"
                    Accessible.name:"Choose mouse button. Current: "+text
                    onClicked:dialog.openValuePicker(this,"Choose mouse button",dialog.mouseButtonChoices,currentValue,function(value){mouseButton.value=value;})
                }
            }
            Item {
                Layout.maximumWidth: visible ? Number.POSITIVE_INFINITY : 0
                visible: dialog.types[actionType.currentIndex]==="key"
                Kirigami.FormData.label: "Key:"
                Layout.fillWidth: true; Layout.preferredWidth: mappingForm.compactControlWidth; Layout.minimumWidth: 0
                Kirigami.FormData.buddyFor: keyPicker
                implicitWidth: keyPicker.implicitWidth
                implicitHeight: keyPicker.implicitHeight+Kirigami.Units.smallSpacing*2
                Button {
                    id:keyPicker; objectName:"keyPicker"
                    width:parent.width; y:Kirigami.Units.smallSpacing
                    readonly property int currentValue:keyCode.value
                    text:dialog.keyLabel(currentValue); icon.name:"input-keyboard"
                    Accessible.name:"Choose keyboard key. Current: "+text
                    onClicked:dialog.openValuePicker(this,"Choose keyboard key",dialog.eventKeyChoices,currentValue,function(value){keyCode.value=value;})
                }
            }
            Label {
                Layout.maximumWidth: visible ? Number.POSITIVE_INFINITY : 0
                visible: dialog.types[actionType.currentIndex]==="key"
                text: "For key combinations, choose Macro / key combination."
                wrapMode: Text.WordWrap; Layout.fillWidth: true; Layout.preferredWidth: mappingForm.compactControlWidth
                color: Kirigami.Theme.disabledTextColor
            }
            Item {
                Layout.maximumWidth: visible ? Number.POSITIVE_INFINITY : 0
                visible: dialog.types[actionType.currentIndex]==="special"
                Kirigami.FormData.label: "Action:"
                Layout.fillWidth: true; Layout.preferredWidth: mappingForm.compactControlWidth; Layout.minimumWidth: 0
                Kirigami.FormData.buddyFor: specialAction
                implicitWidth: specialAction.implicitWidth
                implicitHeight: specialAction.implicitHeight+Kirigami.Units.smallSpacing*2
                ComboBox {
                    id: specialAction; objectName: "specialAction"
                    width: parent.width
                    y: Kirigami.Units.smallSpacing
                    Accessible.name: "Special action"
                    model: backendObject.specialActions || []; textRole: "label"; valueRole: "value"
                }
            }
            Label {
                Layout.maximumWidth: visible ? Number.POSITIVE_INFINITY : 0
                visible: dialog.types[actionType.currentIndex]==="none"
                text: "This button will have no assignment."
                wrapMode: Text.WordWrap; Layout.fillWidth: true; Layout.preferredWidth: mappingForm.compactControlWidth
            }
        }
            Item {
                visible: dialog.types[actionType.currentIndex]==="macro"
                Layout.fillWidth: true; Layout.fillHeight:true; Layout.minimumWidth: 0
                Layout.minimumHeight:eventHeader.implicitHeight+Kirigami.Units.gridUnit*3
                implicitHeight: eventPanel.implicitHeight+Kirigami.Units.largeSpacing
                Frame {
                    id: eventPanel; objectName: "macroEventPanel"
                    y: Kirigami.Units.largeSpacing; width: parent.width; height:parent.height-y
                    padding: 1
                    Kirigami.Theme.colorSet:Kirigami.Theme.View
                    Kirigami.Theme.inherit:false
                    background:Rectangle { color:Kirigami.Theme.backgroundColor; border.color:Kirigami.ColorUtils.linearInterpolation(Kirigami.Theme.backgroundColor,Kirigami.Theme.textColor,Kirigami.Theme.frameContrast) }
                    implicitHeight: eventPanelLayout.implicitHeight+topPadding+bottomPadding
                    contentItem: ColumnLayout {
                        id: eventPanelLayout
                        spacing: 0
                        Kirigami.InlineViewHeader {
                            id:eventHeader; objectName:"macroEventHeader"
                            Layout.fillWidth:true
                            text:"Events"
                            actions:[Kirigami.Action {
                                id:addEventAction; objectName:"macroAddEvent"; text:"Add…"; icon.name:"list-add"
                                enabled:dialog.visualEvents.length<256; onTriggered:dialog.openAddEvent()
                                displayComponent:ToolButton {
                                    objectName:"macroAddEventButton"; action:addEventAction
                                    Accessible.name:"Add macro event"
                                    focusPolicy:Qt.StrongFocus; activeFocusOnTab:true
                                    Keys.onReturnPressed:clicked(); Keys.onEnterPressed:clicked()
                                }
                            }]
                        }
                        ScrollView {
                            id: eventScroll; objectName:"macroEventScroll"
                            Layout.fillWidth:true; Layout.fillHeight:true; Layout.preferredHeight:Kirigami.Units.gridUnit*9; Layout.minimumHeight:Kirigami.Units.gridUnit*3
                            contentWidth:availableWidth; clip:true
                            ListView {
                                id:eventList; objectName:"macroEventList"
                                model:dialog.visualEvents.length
                                implicitHeight:Kirigami.Units.gridUnit*9
                                boundsBehavior:Flickable.StopAtBounds
                                Accessible.name:"Macro events"
                                spacing:Kirigami.Units.smallSpacing
                                delegate: ItemDelegate {
                                    id:eventRow
                                    property alias moveUpControl: moveUpButton
                                    property alias moveDownControl: moveDownButton
                                    required property int index
                                    readonly property var event:dialog.visualEvents[index] || [1,30]
                                    objectName:"macroEventRow"+index
                                    focusPolicy:Qt.StrongFocus; activeFocusOnTab:true
                                    onActiveFocusChanged:if(activeFocus) eventList.positionViewAtIndex(index,ListView.Contain)
                                    Kirigami.Theme.useAlternateBackgroundColor:true
                                    width:eventList.width
                                    topPadding:0; bottomPadding:0
                                    leftPadding:Kirigami.Units.smallSpacing; rightPadding:Kirigami.Units.smallSpacing
                                    Accessible.name:"Event "+(index+1)+", "+(event[0]===1 ? "key down" : event[0]===2 ? "key up" : "delay")+", "+(event[0]===3 ? event[1]+" milliseconds" : dialog.keyLabel(event[1]))
                                    contentItem:RowLayout {
                                    spacing:Kirigami.Units.smallSpacing
                                    Label {
                                        objectName:"macroEventName"+eventRow.index
                                        text:(eventRow.event[0]===1 ? "Key down" : eventRow.event[0]===2 ? "Key up" : "Delay")+" · "+(eventRow.event[0]===3 ? eventRow.event[1]+" ms" : dialog.keyLabel(eventRow.event[1]))
                                        Layout.fillWidth:true; elide:Text.ElideRight
                                    }
                                    ToolButton {
                                        id:moveUpButton; objectName:"macroEventUp"+eventRow.index
                                        focusPolicy:Qt.StrongFocus; activeFocusOnTab:true
                                        Keys.onReturnPressed:clicked(); Keys.onEnterPressed:clicked()
                                        onActiveFocusChanged:if(activeFocus) eventList.positionViewAtIndex(eventRow.index,ListView.Contain)
                                        icon.name:"go-up"; enabled:eventRow.index>0
                                        Accessible.name:"Move event "+(eventRow.index+1)+" up"
                                        ToolTip.visible:hovered; ToolTip.text:Accessible.name
                                        onClicked:dialog.moveEvent(eventRow.index,-1)
                                    }
                                    ToolButton {
                                        id:moveDownButton; objectName:"macroEventDown"+eventRow.index
                                        focusPolicy:Qt.StrongFocus; activeFocusOnTab:true
                                        Keys.onReturnPressed:clicked(); Keys.onEnterPressed:clicked()
                                        onActiveFocusChanged:if(activeFocus) eventList.positionViewAtIndex(eventRow.index,ListView.Contain)
                                        icon.name:"go-down"; enabled:eventRow.index<dialog.visualEvents.length-1
                                        Accessible.name:"Move event "+(eventRow.index+1)+" down"
                                        ToolTip.visible:hovered; ToolTip.text:Accessible.name
                                        onClicked:dialog.moveEvent(eventRow.index,1)
                                    }
                                    ToolButton {
                                        objectName:"macroEventRemove"+eventRow.index
                                        focusPolicy:Qt.StrongFocus; activeFocusOnTab:true
                                        Keys.onReturnPressed:clicked(); Keys.onEnterPressed:clicked()
                                        onActiveFocusChanged:if(activeFocus) eventList.positionViewAtIndex(eventRow.index,ListView.Contain)
                                        icon.name:"edit-delete"
                                        Accessible.name:"Remove event "+(eventRow.index+1)
                                        ToolTip.visible:hovered; ToolTip.text:Accessible.name
                                        onClicked:dialog.removeEvent(eventRow.index)
                                    }
                                    }
                                }
                                Label { anchors.centerIn:parent; visible:dialog.visualEvents.length===0; text:"No events. Add an event to begin."; width:parent.width; wrapMode:Text.WordWrap; horizontalAlignment:Text.AlignHCenter; color:Kirigami.Theme.disabledTextColor }
                            }
                        }
                    }
                }
            }
            Kirigami.InlineMessage {
                Layout.maximumWidth: visible ? Number.POSITIVE_INFINITY : 0
                objectName: "mappingValidation"
                Kirigami.FormData.isSection: true
                text: dialog.validation; visible: dialog.validation!==""
                type: Kirigami.MessageType.Error
                Layout.fillWidth: true; Layout.preferredWidth: mappingForm.controlWidth
            }
        }
    }
}
