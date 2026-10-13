import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kirigami.dialogs as KirigamiDialogs

KirigamiDialogs.Dialog {
    id: picker
    objectName: "valuePicker"
    property var hostItem: null
    property bool initialSelectionPending:false
    onAboutToShow: { if(hostItem) parent=hostItem; initialSelectionPending=true; pendingValue=-1; search.text=""; }
    onFilteredChoicesChanged: if(visible && !initialSelectionPending) {
        pendingValue=-1;
        Qt.callLater(function(){values.forceLayout(); values.currentIndex=-1; values.positionViewAtBeginning();});
    }
    property var choices: []
    property int selectedValue: -1
    property int pendingValue: -1
    readonly property bool selectionValid: eventMode && eventKind===3 ? delay.value>=1 && delay.value<=60000 : filteredChoices.some(function(choice){return choice.value===pendingValue && choice.selectable!==false;})
    property var opener: null
    property var acceptValue: null
    property string contextToken: ""
    property bool eventMode: false
    property bool allowDelay: true
    property int eventKind: 1
    property var contextCheck: null
    readonly property var filteredChoices: {
        let words=search.text.trim().toLowerCase().split(/\s+/).filter(function(word){return word.length>0;});
        return choices.filter(function(choice) {
            let searchable=(choice.label+" "+choice.value).toLowerCase();
            return words.every(function(word){return searchable.indexOf(word)>=0;});
        });
    }
    modal: true
    preferredWidth: Kirigami.Units.gridUnit*30
    preferredHeight: Kirigami.Units.gridUnit*30
    maximumWidth: Math.min(Kirigami.Units.gridUnit*30,hostItem ? hostItem.width-Kirigami.Units.largeSpacing*4 : Kirigami.Units.gridUnit*30)
    maximumHeight: Math.min(Kirigami.Units.gridUnit*30,hostItem ? hostItem.height-Kirigami.Units.largeSpacing*4 : Kirigami.Units.gridUnit*30)
    width:maximumWidth
    height:maximumHeight
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    standardButtons: Dialog.Ok | Dialog.Cancel
    onAccepted: {
        if(!selectionValid || contextCheck && !contextCheck(contextToken)) return;
        if(acceptValue) acceptValue(eventMode && eventKind===3 ? delay.value : pendingValue,eventKind);
    }
    onOpened: {
        let cancel=standardButton(Dialog.Cancel); if(cancel) cancel.objectName="valuePickerCancel";
        let ok=standardButton(Dialog.Ok); if(ok) {ok.objectName="valuePickerOk";ok.enabled=Qt.binding(function(){return picker.selectionValid;});}
        search.forceActiveFocus(Qt.PopupFocusReason);
        Qt.callLater(function() {
            values.forceLayout();
            let current=picker.filteredChoices.findIndex(function(choice){return choice.value===picker.selectedValue;});
            values.currentIndex=current;
            picker.pendingValue=current>=0 ? picker.filteredChoices[current].value : -1;
            if(current>=0) values.positionViewAtIndex(current,ListView.Center); else values.positionViewAtBeginning();
            picker.initialSelectionPending=false;
            initialRevealTimer.restart();
        });
    }
    onClosed: {
        initialRevealTimer.stop();
        let previous=opener;
        acceptValue=null;
        Qt.callLater(function(){if(previous && previous.visible) previous.forceActiveFocus(Qt.PopupFocusReason);});
    }
    Timer {
        id:initialRevealTimer
        interval:1
        onTriggered: if(picker.visible && values.currentIndex>=0) {
            // Selected bold text can settle one layout pass after currentIndex.
            values.forceLayout();
            values.positionViewAtIndex(values.currentIndex,ListView.Center);
        }
    }
    function selectIndex(index) {
        if(index<0 || index>=filteredChoices.length || filteredChoices[index].selectable===false) return;
        values.currentIndex=index;
        pendingValue=filteredChoices[index].value;
    }
    function confirmSelection() { if(selectionValid) accept(); }
    Item {
        implicitWidth: Math.max(0,picker.width-picker.leftPadding-picker.rightPadding)
        implicitHeight: Math.min(Kirigami.Units.gridUnit*24,picker.contentItem.availableHeight)
        height: implicitHeight
        ColumnLayout {
        anchors.fill:parent
        anchors.margins:Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing
        RowLayout {
            visible:picker.eventMode
            Layout.fillWidth:true
                        Label { text:"Event:" }
            ComboBox {
                objectName:"valuePickerEventType"
                model:picker.allowDelay ? ["Key down","Key up","Delay"] : ["Key down","Key up"]
                currentIndex:picker.eventKind-1
                Accessible.name:"New event type"
                onActivated:picker.eventKind=currentIndex+1
                Layout.fillWidth:true
            }
        }
        RowLayout {
            visible:picker.eventMode && picker.eventKind===3
            Layout.fillWidth:true
                        Label { text:"Delay:" }
            SpinBox { id:delay; objectName:"valuePickerDelay"; from:1;to:60000;value:100;editable:true;Accessible.name:"Delay in milliseconds";Layout.fillWidth:true }
            Label { text:"ms" }
        }
        Item { visible:picker.eventMode && picker.eventKind===3; Layout.fillHeight:true }
        Kirigami.SearchField {
            id:search; objectName:"valuePickerSearch"
            visible:!picker.eventMode || picker.eventKind!==3
            Layout.fillWidth:true
            placeholderText:"Search by name or number…"
            Accessible.name:"Search available values"
            Keys.onDownPressed: { if(values.currentIndex<0 && values.count>0) values.currentIndex=0; values.forceActiveFocus(Qt.TabFocusReason); }
            Keys.onUpPressed: { values.currentIndex=picker.filteredChoices.length-1; values.forceActiveFocus(Qt.TabFocusReason); }
            Keys.onReturnPressed: picker.confirmSelection()
            Keys.onEnterPressed: picker.confirmSelection()
        }
        ScrollView {
            id:valuesScroll; objectName:"valuePickerScroll"
            implicitWidth:Kirigami.Units.gridUnit*20
            implicitHeight:Kirigami.Units.gridUnit*12
            ScrollBar.vertical.policy:ScrollBar.AlwaysOn
            Component.onCompleted:ScrollBar.vertical.objectName="valuePickerScrollBar"
            background:Frame { padding:Kirigami.Units.smallSpacing }
            visible:!picker.eventMode || picker.eventKind!==3
            Layout.fillWidth:true; Layout.fillHeight:true
            contentWidth:availableWidth
            ListView {
                id:values; objectName:"valuePickerList"
                clip:true; model:picker.filteredChoices
                keyNavigationEnabled:true
                currentIndex:-1
                onCurrentIndexChanged: if(!picker.initialSelectionPending) picker.pendingValue=currentIndex>=0 && currentIndex<picker.filteredChoices.length ? picker.filteredChoices[currentIndex].value : -1
                boundsBehavior:Flickable.StopAtBounds
                Accessible.name:picker.title
                Keys.onReturnPressed:picker.confirmSelection()
                Keys.onEnterPressed:picker.confirmSelection()
                delegate:ItemDelegate {
                    id:valueRow
                    required property int index
                    required property var modelData
                    objectName:"valuePickerOption"+modelData.value
                    width:values.width
                    text:modelData.label+" ("+modelData.value+")"
                    highlighted:values.currentIndex===index
                    font.bold:highlighted || modelData.value===picker.pendingValue
                    icon.name:modelData.value===picker.pendingValue ? "emblem-ok-symbolic" : ""
                    Accessible.name:text
                    Accessible.selected:modelData.value===picker.pendingValue
                    focusPolicy:Qt.StrongFocus; activeFocusOnTab:true
                    onClicked:picker.selectIndex(index)
                    onActiveFocusChanged:if(activeFocus) { values.currentIndex=index; values.positionViewAtIndex(index,ListView.Contain); }
                    Keys.onReturnPressed:picker.confirmSelection()
                    Keys.onEnterPressed:picker.confirmSelection()
                    Keys.onDownPressed: { values.currentIndex=Math.min(values.count-1,index+1); values.forceActiveFocus(Qt.TabFocusReason); }
                    Keys.onUpPressed: { values.currentIndex=Math.max(0,index-1); values.forceActiveFocus(Qt.TabFocusReason); }
                }
                Label {
                    objectName:"valuePickerEmpty"
                    visible:picker.filteredChoices.length===0
                    anchors.centerIn:parent
                    width:parent.width
                    text:"No matching values"; horizontalAlignment:Text.AlignHCenter; wrapMode:Text.WordWrap
                    color:Kirigami.Theme.disabledTextColor
                }
            }
        }
    }
    }
}
