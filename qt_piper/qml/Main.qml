import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

ApplicationWindow {
    id: root
    objectName: "piperWindow"
    width: 1400; height: 820
    minimumWidth: 960; minimumHeight: 700
    visible: true; title: "Piper"
    readonly property bool darkMode: desktopStyle.dark
    readonly property color surface: Kirigami.Theme.backgroundColor
    readonly property color foreground: Kirigami.Theme.textColor
    readonly property color subtle: Kirigami.Theme.disabledTextColor
    readonly property color accent: Kirigami.Theme.highlightColor
    readonly property color line: Kirigami.Theme.disabledTextColor
    readonly property bool defaultsAvailable:false
    readonly property bool defaultsDiffer:false
    property bool assignmentEditing: false
    property real assignmentReturnScroll: 0
    property int quickMacroIndex: -1
    property var quickMacroContext: ({})
    property string quickMacroError: ""
    readonly property string quickMacroPreview: {
        let names=[];
        for(let event of macroRecorder.events) if(event[0]===1) {
            let name="Key "+event[1];
            for(let key of backend.keyChoices) if(key.value===event[1]) { name=key.label; break; }
            names.push(name);
        }
        return names.join(" + ") || "Press your shortcut…";
    }
    function startQuickMacro(index) {
        if(backend.busy || assignmentEditing) return;
        if(quickMacroIndex>=0 && quickMacroIndex!==index) { quickMacroError="Finish or cancel the current recording first."; return; }
        quickMacroContext=backend.captureMappingContext(index);
        if(!backend.mappingContextValid(quickMacroContext)) return;
        quickMacroIndex=index; selectedButton=index; quickMacroError="";
        macroRecorder.start(false);
        root.scheduleAssignmentReveal(index);
    }
    function focusQuickMacro(index) {
        Qt.callLater(function() {
            for(let i=0;i<assignmentRepeater.count;i++) {
                let row=assignmentRepeater.itemAt(i);
                if(row.modelData.index===index) { root.scheduleAssignmentReveal(index); row.quickMacroAction.forceActiveFocus(Qt.OtherFocusReason); return; }
            }
        });
    }
    function finishQuickMacro() {
        let index=quickMacroIndex;
        if(macroRecorder.active) macroRecorder.stop();
        if(macroRecorder.error) { quickMacroError=macroRecorder.error; return; }
        if(!backend.mappingContextValid(quickMacroContext)) { quickMacroError="This assignment changed. Cancel and start a new recording."; return; }
        if(!macroRecorder.events.length) { quickMacroError="No shortcut was recorded. Record again or cancel."; return; }
        if(!backend.stageMapping(quickMacroContext,"macro",macroRecorder.events)) { quickMacroError=backend.error; return; }
        quickMacroIndex=-1; quickMacroError=""; quickMacroContext=({});
        focusQuickMacro(index);
    }
    function cancelQuickMacro() {
        let index=quickMacroIndex;
        if(macroRecorder.active) macroRecorder.stop();
        quickMacroIndex=-1; quickMacroError=""; quickMacroContext=({});
        if(index>=0) focusQuickMacro(index);
    }
    function revertProfileAssignments() {
        cancelQuickMacro();
        backend.resetMappings(backend.captureMappingContexts());
    }
    function applyProfileAssignments() {
        if(quickMacroIndex<0 && !backend.busy && backend.connected) backend.applyMappings(backend.captureMappingContexts());
    }
    Connections {
        target: backend
        function onChanged() {
            root.refreshSettingsPageContext();
            if(root.quickMacroIndex>=0 && !backend.mappingContextValid(root.quickMacroContext)) {
                if(macroRecorder.active) macroRecorder.stop();
                root.quickMacroError="This assignment changed. Cancel and start a new recording.";
            }
        }
    }
    property var pendingAssignmentNavigation: null
    property bool applyThenNavigate: false
    function requestNavigation(action) {
        if(backend.busy || assignmentPage.applying) { restoreSelectors(); return; }
        if(quickMacroIndex>=0) { quickMacroError="Finish or cancel the current recording before leaving."; restoreSelectors(); return; }
        if(assignmentEditing && macroRecorder.active) assignmentPage.cancelRecording();
        if(assignmentEditing && assignmentPage.edited) {
            pendingAssignmentNavigation=action;
            assignmentNavigationDialog.open();
            restoreSelectors();
            return;
        }
        assignmentEditing=false;
        action();
    }
    function restoreSelectors() {
        deviceSelector.currentIndex=Qt.binding(function() { return backend.selectedDeviceIndex; });
        profileSelector.currentIndex=Qt.binding(function() { return backend.selectedProfileIndex; });
        for(let i=0;i<navigationRepeater.count;i++) {
            let group=navigationRepeater.itemAt(i);
            group.sectionControl.checked=Qt.binding(function() { return root.page===group.modelData.page && !(root.assignmentEditing && group.modelData.page===1); });
        }
    }
    function completeAssignmentNavigation() {
        let action=pendingAssignmentNavigation;
        pendingAssignmentNavigation=null; applyThenNavigate=false;
        assignmentNavigationDialog.close();
        assignmentEditing=false;
        if(action) action();
    }
    function navigatePage(nextPage) { requestNavigation(function() { root.page=nextPage; }); }
    property int page: 1
    readonly property string pageScope: ["sensitivity","","lighting","advanced","profiles"][page]
    property var settingsPageContext: ({})
    readonly property bool settingsPageDirty: {
        let changed=backend.dirty;
        return pageScope!=="" && settingsPageContext.token!==undefined && backend.pageDirty(settingsPageContext);
    }
    readonly property string assignmentTitle: {
        let mapping=assignmentPage.mapping;
        let label=device.hasGShift && mapping.physicalIndex>=8 ? "G"+(mapping.physicalIndex+1) : "Button "+(Number(mapping.physicalIndex)+1);
        return label+(device.hasGShift ? " · "+(mapping.layer==="gshift" ? "G-Shift" : "Normal") : "");
    }
    function refreshSettingsPageContext() {
        if(pageScope!=="" && backend.connected && !backend.busy && profile.path) settingsPageContext=backend.capturePageContext(pageScope);
    }
    onPageChanged: refreshSettingsPageContext()
    readonly property string pageTitle: ["Sensitivity", "Buttons", "Lighting", "Advanced", "Profiles"][page]
    readonly property var navigationItems: [
        {name: "buttonsTab", title: "Buttons", icon: "input-mouse", page: 1},
        {name: "sensitivityTab", title: "Sensitivity", icon: "speedometer", page: 0},
        {name: "lightingTab", title: "Lighting", icon: "color-management", page: 2},
        {name: "profileTab", title: "Profiles", icon: "view-list-icons", page: 4},
        {name: "advancedTab", title: "Advanced", icon: "settings-configure", page: 3}
    ]
    property int searchResultIndex: 0
    readonly property var searchResults: {
        let query=searchField.text.trim().toLowerCase();
        if (!query) return [];
        let terms=query.replace(/-/g," ").split(/\s+/);
        let entries=[];
        let aliases=["dpi polling pointer speed", "button assignment binding shortcut mouse", "led color colour rgb brightness", "debounce angle snapping", "profile name active enabled"];
        for (let section of root.navigationItems) {
            entries.push({kind:"section", title:section.title, detail:"Settings section", icon:section.icon, page:section.page, search:(section.title+" "+aliases[section.page]).toLowerCase()});
        }
        for (let button of root.buttons) {
            let name=root.device.hasGShift && button.physicalIndex>=8 ? root.labelFor(button) : "Button "+(button.physicalIndex+1);
            let layer=root.device.hasGShift ? (button.layer==="gshift" ? "G-Shift" : "Normal") : "Current profile";
            entries.push({kind:"assignment", title:name, detail:button.actionLabel+" · "+layer, icon:"input-mouse", index:button.index, shifted:button.layer==="gshift", search:(name+" button "+(button.physicalIndex+1)+" "+button.actionLabel+" "+layer+" "+(button.layer==="gshift" ? "gshift" : "")).toLowerCase().replace(/-/g," ")});
        }
        return entries.filter(function(entry) { return terms.every(function(term) { return entry.search.indexOf(term)!==-1; }); });
    }
    readonly property var searchAssignments: searchResults.map(function(result,index) { return {result:result,resultIndex:index}; }).filter(function(entry) { return entry.result.kind==="assignment" && !(root.assignmentEditing && entry.result.index===assignmentPage.buttonIndex); })
    onSearchResultsChanged: searchResultIndex=Math.max(0,Math.min(searchResultIndex,searchResults.length-1))
    function revealSearchResult(index) {
        let result=searchResults[index];
        if (!result) return;
        let item=null;
        if (result.kind==="section") {
            for (let i=0;i<navigationRepeater.count;i++) {
                let group=navigationRepeater.itemAt(i);
                if (group.modelData.page===result.page) item=group.sectionControl;
            }
        } else {
            if(root.assignmentEditing && result.index===assignmentPage.buttonIndex) item=navigationRepeater.itemAt(0).childControl;
            let repeater=navigationRepeater.itemAt(0).resultRepeater;
            for (let i=0;i<repeater.count;i++) {
                let candidate=repeater.itemAt(i);
                if (candidate.modelData.resultIndex===index) item=candidate;
            }
        }
        let flickable=navigationPage.flickable;
        if (!item || !flickable) return;
        let top=item.mapToItem(flickable.contentItem,0,0).y;
        let bottom=top+item.height;
        if (top<flickable.contentY) flickable.contentY=Math.max(0,top);
        else if (bottom>flickable.contentY+flickable.height) flickable.contentY=Math.max(0,bottom-flickable.height);
    }
    function moveSearchResult(direction) {
        if (!searchResults.length) return;
        searchResultIndex=(searchResultIndex+direction+searchResults.length)%searchResults.length;
        revealSearchResult(searchResultIndex);
    }
    function activateSearchResult(index) {
        let result=searchResults[index];
        if (!result) return;
        root.requestNavigation(function() {
        root.searchResultIndex=index;
        if (result.kind==="section") {
            root.page=result.page;
            contentPane.forceActiveFocus(Qt.OtherFocusReason);
        } else {
            root.page=1;
            root.shifted=result.shifted;
            root.selectedButton=result.index;
            Qt.callLater(function() {
                root.scheduleAssignmentReveal(result.index);
                diagramArea.forceActiveFocus(Qt.OtherFocusReason);
            });
        }
        });
    }
    property bool shifted: false
    property int selectedButton: -1
    property int selectedLed: -1
    property string hoverTarget: ""
    property bool keyboardTargetActive: false
    property var device: backend.selectedDevice
    property var profile: backend.selectedProfile
    property var buttons: profile.buttons || []
    property var leds: profile.leds || []
    property var resolutions: profile.resolutions || []
    property var layerButtons: buttons.filter(function(b) { return !device.hasGShift || b.layer===(shifted?"gshift":"normal") })
    property var visibleAssignments: page===2 ? leds : layerButtons
    property int diagramCount: page === 2 ? (leds.length || -1) : (buttons.length || -1)
    property var diagram: diagrams.describe(device.svg || "", page === 2 ? "leds" : "buttons", diagramCount, shifted)
    property var bounds: diagram.deviceBounds || ({x:0,y:0,width:diagram.width,height:diagram.height})
    property string selectedTarget: page === 2 ? (selectedLed < 0 ? "" : "led"+selectedLed) : (selectedButton < 0 ? "" : "button"+(shifted ? selectedButton-21 : selectedButton))
    property bool hasSelection: page===2 ? selectedLed>=0 : selectedButton>=0
    // Pointer feedback ends at a miss. A remembered row selection is not a hover.
    readonly property string diagramHighlight: hoverTarget || (diagramArea.activeFocus && keyboardTargetActive ? selectedTarget : "")
    readonly property string selectedTargetDescription: !hasSelection ? "No target selected." : page===2 ? "Lighting zone "+(selectedLed+1) : "Button "+(buttonAt(selectedButton).physicalIndex+1)+", "+(buttonAt(selectedButton).actionLabel||"No assignment")
    property bool discardOnClose: false
    function buttonAt(index) { for(let b of buttons) if(b.index===index) return b; return {} }
    function ledAt(index) { for(let l of leds) if(l.index===index) return l; return {} }
    function compactMapping(b) { return b.actionType==="macro" || b.actionType==="key" ? b.actionLabel.replace(/Left /g, "").replace(/Right /g, "R ") : b.actionLabel }
    function labelFor(b) { return device.hasGShift && b.physicalIndex>=8 ? "G"+(b.physicalIndex+1) : String(b.physicalIndex+1) }
    function openButton(index) {
        requestNavigation(function() {
        selectedButton=index;
        assignmentReturnScroll=assignmentsScroll.contentItem.contentY;
        assignmentPage.load(buttonAt(index));
        assignmentEditing=true;
        Qt.callLater(function() { assignmentPage.focusFirst(); });
        });
    }
    function returnToAssignments() {
        requestNavigation(function() {
        Qt.callLater(function() {
            assignmentsScroll.contentItem.contentY=assignmentReturnScroll;
            for(let i=0;i<assignmentRepeater.count;i++) {
                let row=assignmentRepeater.itemAt(i);
                if(row.modelData.index===selectedButton) row.forceActiveFocus(Qt.OtherFocusReason);
            }
        });
        });
    }
    function openLed(index) { selectedLed=index; ledDialog.load(ledAt(index)); ledDialog.open() }
    function chooseTarget(index) { if(page===2) { if(ledAt(index).index!==undefined) openLed(index) } else if(buttonAt(index).index!==undefined) openButton(index) }
    function scheduleAssignmentReveal(index) {
        assignmentRevealTimer.targetIndex=index;
        assignmentRevealTimer.restart();
    }
    Timer {
        id: assignmentRevealTimer
        property int targetIndex: -1
        interval: 16; repeat: false
        onTriggered: root.revealAssignment(targetIndex)
    }
    function revealAssignment(index) {
        for (let i=0; i<assignmentRepeater.count; ++i) {
            let row=assignmentRepeater.itemAt(i);
            if (!row || row.modelData.index!==index) continue;
            let scroll=assignmentsScroll.contentItem;
            let top=row.mapToItem(scroll.contentItem,0,0).y;
            if (top<scroll.contentY) scroll.contentY=Math.max(0,top);
            else if (top+row.height>scroll.contentY+scroll.height) scroll.contentY=Math.max(0,top+row.height-scroll.height);
            return;
        }
    }
    function selectDiagramTarget(index) {
        keyboardTargetActive=false;
        if (page===2) { chooseTarget(index); return; }
        if (buttonAt(index).index===undefined) return;
        selectedButton=index;
        root.scheduleAssignmentReveal(index);
    }
    function nextTarget(direction) { let list=diagram.hotspots||[]; if(!list.length)return; hoverTarget=""; keyboardTargetActive=true; let idx=list.findIndex(function(h){return h.index===(page===2?selectedLed:selectedButton)}); idx=idx<0 ? (direction>0 ? 0 : list.length-1) : (idx+direction+list.length)%list.length; if(page===2)selectedLed=list[idx].index;else { selectedButton=list[idx].index; root.scheduleAssignmentReveal(root.selectedButton); } }
    function clearSelection() { selectedButton=-1; selectedLed=-1; hoverTarget=""; keyboardTargetActive=false }
    function revealSettingsFocus(scroll) {
        let item = root.activeFocusItem;
        if (!item || !scroll.visible) return;
        let ancestor = item;
        while (ancestor && ancestor !== scroll.contentItem) ancestor = ancestor.parent;
        if (!ancestor) return;
        let flickable = scroll.contentItem;
        let top = item.mapToItem(flickable.contentItem, 0, 0).y;
        let bottom = top + item.height;
        if (top < flickable.contentY) flickable.contentY = Math.max(0, top);
        else if (bottom > flickable.contentY + flickable.height) flickable.contentY = Math.max(0, bottom-flickable.height);
    }
    onClosing: function(event) {
        if (backend.busy) { event.accepted=false; return; }
        if(quickMacroIndex>=0 && !discardOnClose) { event.accepted=false; quickMacroError="Finish or cancel the current recording before closing."; return; }
        if(assignmentEditing && macroRecorder.active) assignmentPage.cancelRecording();
        if (assignmentEditing && assignmentPage.edited && !discardOnClose) {
            event.accepted=false;
            requestNavigation(function() { root.close(); });
            return;
        }
        if (backend.dirty && !discardOnClose) { event.accepted=false; closeDialog.open(); }
    }
    Shortcut { sequence: "Ctrl+Return"; onActivated: {
        if(root.assignmentEditing) assignmentPage.applyDraft();
        else if(root.page===1) root.applyProfileAssignments();
        else if(root.settingsPageDirty && !backend.busy && backend.connected) backend.applyPage(root.settingsPageContext);
    } }
    readonly property string contextHelpTopic: root.assignmentEditing ? assignmentPage.helpTopic : ["sensitivity","buttons","lighting","advanced","profiles"][root.page]
    readonly property bool contextHelpAvailable: handbook.hasTopic(contextHelpTopic)
    function stopCaptureForHelp() {
        if(root.assignmentEditing) assignmentPage.cancelRecording();
        else if(macroRecorder.active) macroRecorder.stop();
        if(root.quickMacroIndex>=0 && macroRecorder.error) root.quickMacroError=macroRecorder.error;
    }
    function openContextHelp() { if(contextHelpAvailable) { stopCaptureForHelp(); handbook.showTopic(contextHelpTopic); } }
    Shortcut { sequences:[StandardKey.HelpContents]; enabled:root.contextHelpAvailable; onActivated:root.openContextHelp() }
    Action {
        id:contextHelpAction; objectName:"contextHelpAction"
        text:"Help"; icon.name:"help-contents"
        enabled:root.contextHelpAvailable
        onTriggered:root.openContextHelp()
    }
    Action {
        id: handbookAction
        objectName: "handbookAction"
        text: "Piper Kirigami Handbook"
        icon.name: "help-contents"
        onTriggered: { root.stopCaptureForHelp(); handbook.showHelp(); }
    }
    // System Settings embeds its navigation and module as separate Kirigami surfaces.
    ToolButton { id: headerMeasure; visible: false; icon.name: "application-menu"; display: AbstractButton.IconOnly }
    readonly property real paneHeaderHeight: headerMeasure.implicitHeight+Kirigami.Units.smallSpacing*2
    RowLayout {
        // Both embedded ApplicationItems register Back shortcuts. Claim this
        // child-page chord before their duplicate native shortcuts compete.
        Keys.onShortcutOverride: function(event) {
            if(root.assignmentEditing && !macroRecorder.active && event.key===Qt.Key_Left && event.modifiers===Qt.AltModifier) {
                event.accepted=true;
                Qt.callLater(root.returnToAssignments);
            }
        }
        anchors.fill: parent; spacing: 0
        Item {
            Layout.fillHeight: true
            Layout.preferredWidth: Kirigami.Units.gridUnit*15
            Layout.minimumWidth: Layout.preferredWidth
            Layout.maximumWidth: Layout.preferredWidth
        Kirigami.ApplicationItem {
            id: navigationSidebar
            objectName: "navigationSidebar"
            anchors.fill: parent
            pageStack.globalToolBar.style: Kirigami.ApplicationHeaderStyle.None
            pageStack.initialPage: Kirigami.ScrollablePage {
                id: navigationPage
                title: ""; padding: 0
                globalToolBarStyle: Kirigami.ApplicationHeaderStyle.None
                Kirigami.Theme.colorSet: Kirigami.Theme.View
                Kirigami.Theme.inherit: false
                header: Kirigami.AbstractApplicationHeader {
                    id: navigationHeader
                    objectName: "navigationHeader"
                    page: navigationPage; pageRow: navigationSidebar.pageStack
                    minimumHeight: root.paneHeaderHeight; preferredHeight: minimumHeight; maximumHeight: minimumHeight; height: minimumHeight
                    leftPadding: Kirigami.Units.largeSpacing; rightPadding: Kirigami.Units.smallSpacing
                    RowLayout {
                        width: parent.width
                        spacing: Kirigami.Units.smallSpacing
                    Kirigami.SearchField {
                        id: searchField
                        objectName: "settingsSearch"
                        Accessible.name: "Search settings and button assignments"
                        placeholderText: "Search settings…"
                        autoAccept: false
                        Layout.fillWidth: true
                        Layout.minimumWidth: Kirigami.Units.gridUnit*7
                        onTextChanged: { root.searchResultIndex=0; Qt.callLater(function() { root.revealSearchResult(0); }); }
                        Keys.onDownPressed: root.moveSearchResult(1)
                        Keys.onUpPressed: root.moveSearchResult(-1)
                        Keys.onReturnPressed: root.activateSearchResult(root.searchResultIndex)
                        Keys.onEnterPressed: root.activateSearchResult(root.searchResultIndex)
                        Keys.onEscapePressed: contentPane.forceActiveFocus(Qt.OtherFocusReason)
                    }
                    ToolButton {
                        objectName: "appMenuButton"; icon.name: "application-menu"; text: "Menu"; display: AbstractButton.IconOnly
                        onClicked: appMenu.open(); ToolTip.text: "Menu"; ToolTip.visible: hovered
                        Menu { id: appMenu
                            MenuItem { text: root.darkMode ? "Breeze Light" : "Breeze Dark"; objectName: "themeToggle"; icon.name: "preferences-desktop-theme-global"; onTriggered: desktopStyle.setDark(!desktopStyle.dark) }
                            MenuItem { text: "Refresh devices"; icon.name: "view-refresh"; enabled: !backend.dirty && !backend.busy; onTriggered: backend.refresh() }
                            MenuSeparator {}
                            MenuItem { objectName: "handbookMenuItem"; action: handbookAction }
                        }
                    }
                    }
                }
                    ColumnLayout {
                        id: navigationList
                        width: navigationPage.availableWidth
                        spacing: 0
                        Item { Layout.preferredHeight: Kirigami.Units.smallSpacing }
                        ButtonGroup { id: navigationGroup }
                        Repeater {
                            id: navigationRepeater
                            model: root.navigationItems
                            delegate: ColumnLayout {
                                required property var modelData
                                required property int index
                                property alias childControl: activeAssignmentEntry
                                property alias sectionControl: sectionControl
                                property alias resultRepeater: inlineResultsRepeater
                                Layout.fillWidth: true
                                spacing: 0
                            ItemDelegate {
                                id: sectionControl
                                objectName: modelData.name
                                Layout.fillWidth: true
                                text: modelData.title
                                icon.name: modelData.icon
                                leftPadding: Kirigami.Units.largeSpacing
                                rightPadding: Kirigami.Units.largeSpacing
                                checkable: true
                                ButtonGroup.group: navigationGroup
                                checked: root.page===modelData.page && !(root.assignmentEditing && modelData.page===1)
                                highlighted: checked || (!root.assignmentEditing && searchField.activeFocus && root.searchResults.length>0 && root.searchResults[root.searchResultIndex].kind==="section" && root.searchResults[root.searchResultIndex].page===modelData.page)
                                font.bold: searchField.text.trim().length>0 && root.searchResults.some(function(result) { return result.kind==="section" && result.page===modelData.page; })
                                focusPolicy: Qt.StrongFocus
                                activeFocusOnTab: true
                                Accessible.name: modelData.title
                                Accessible.role: Accessible.PageTab
                                Accessible.selected: checked
                                onClicked: root.navigatePage(modelData.page)
                                function navigateTo(next) {
                                    root.requestNavigation(function() {
                                        root.page=root.navigationItems[next].page;
                                        navigationRepeater.itemAt(next).sectionControl.forceActiveFocus(Qt.TabFocusReason);
                                    });
                                }
                                Keys.onDownPressed: navigateTo((index+1)%root.navigationItems.length)
                                Keys.onUpPressed: navigateTo((index+root.navigationItems.length-1)%root.navigationItems.length)
                                Keys.onPressed: function(event) {
                                    if (event.key===Qt.Key_Home) { navigateTo(0); event.accepted=true; }
                                    else if (event.key===Qt.Key_End) { navigateTo(root.navigationItems.length-1); event.accepted=true; }
                                }
                                Keys.onReturnPressed: root.navigatePage(modelData.page)
                                Keys.onEnterPressed: root.navigatePage(modelData.page)
                                ToolTip.visible: false
                                ToolTip.text: modelData.title
                            }
                                ItemDelegate {
                                    id: activeAssignmentEntry
                                    objectName: index===0 ? "assignmentSidebarEntry" : ""
                                    visible: index===0 && root.assignmentEditing
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: Math.max(implicitHeight,sectionControl.implicitHeight)
                                    leftPadding: Kirigami.Units.gridUnit*2
                                    rightPadding: Kirigami.Units.largeSpacing
                                    text: root.assignmentTitle
                                    icon.name: "input-mouse"
                                    highlighted: true
                                    focusPolicy: Qt.StrongFocus; activeFocusOnTab: true
                                    Accessible.name: text+", assignment settings"
                                    Accessible.selected: true
                                    onClicked: assignmentPage.focusFirst()
                                    Keys.onReturnPressed: assignmentPage.focusFirst()
                                    Keys.onEnterPressed: assignmentPage.focusFirst()
                                    contentItem: RowLayout {
                                        spacing: Kirigami.Units.smallSpacing
                                        Kirigami.Icon { source: activeAssignmentEntry.icon.name; Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium; Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium; selected: true; Accessible.ignored: true }
                                        Label { Layout.fillWidth: true; text: activeAssignmentEntry.text; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter; color: Kirigami.Theme.highlightedTextColor }
                                    }
                                    ToolTip.visible: hovered; ToolTip.text: text
                                }
                                ColumnLayout {
                                    objectName: index===0 ? "searchResults" : ""
                                    Layout.fillWidth: true
                                    visible: index===0 && root.searchAssignments.length>0
                                    spacing: 0
                                    Repeater {
                                        id: inlineResultsRepeater
                                        model: index===0 ? root.searchAssignments : []
                                        delegate: ItemDelegate {
                                            id: inlineResult
                                            required property var modelData
                                            objectName: "searchResult"+modelData.resultIndex
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: Math.max(implicitHeight,sectionControl.implicitHeight)
                                            leftPadding: Kirigami.Units.gridUnit*2
                                            rightPadding: Kirigami.Units.largeSpacing
                                            focusPolicy: Qt.StrongFocus
                                            activeFocusOnTab: true
                                            icon.name: "input-mouse"
                                            text: modelData.result.title+(root.device.hasGShift ? " · "+(modelData.result.shifted ? "G-Shift" : "Normal") : "")
                                            highlighted: (root.page===1 && root.selectedButton===modelData.result.index && root.shifted===modelData.result.shifted) || (searchField.activeFocus && root.searchResultIndex===modelData.resultIndex)
                                            Accessible.name: modelData.result.title+", "+modelData.result.detail
                                            Accessible.selected: highlighted
                                            onClicked: root.activateSearchResult(modelData.resultIndex)
                                            onActiveFocusChanged: if(activeFocus) { root.searchResultIndex=modelData.resultIndex; root.revealSearchResult(modelData.resultIndex); }
                                            Keys.onReturnPressed: root.activateSearchResult(modelData.resultIndex)
                                            Keys.onEnterPressed: root.activateSearchResult(modelData.resultIndex)
                                            contentItem: RowLayout {
                                                spacing: Kirigami.Units.smallSpacing
                                                Kirigami.Icon { source: inlineResult.icon.name; Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium; Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium; selected: inlineResult.highlighted; Accessible.ignored: true }
                                                Label {
                                                    objectName: "searchResultLabel"+inlineResult.modelData.resultIndex
                                                    Layout.fillWidth: true
                                                    text: inlineResult.text
                                                    elide: Text.ElideRight
                                                    wrapMode: Text.NoWrap
                                                    verticalAlignment: Text.AlignVCenter
                                                    color: inlineResult.highlighted ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
                                                }
                                            }
                                        }
                                    }
                                }
                                Label {
                                    objectName: index===0 ? "searchNoResults" : ""
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: Kirigami.Units.gridUnit*1.75
                                    leftPadding: Kirigami.Units.gridUnit*2
                                    rightPadding: Kirigami.Units.largeSpacing
                                    visible: index===0 && searchField.text.trim().length>0 && root.searchResults.length===0
                                    text: "No matches"
                                    elide: Text.ElideRight
                                    verticalAlignment: Text.AlignVCenter
                                    color: Kirigami.Theme.disabledTextColor
                                }
                            }
                        }
                    }
            }
        }
        }
        Item {
            objectName: "paneDivider"
            Layout.fillHeight: true; Layout.preferredWidth: 1
            Kirigami.Separator { width: parent.width; y: root.paneHeaderHeight; height: parent.height-y }
        }
        Item {
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumWidth: 0
        Kirigami.ApplicationItem {
            id: modulePane
            objectName: "modulePane"
            anchors.fill: parent
            pageStack.globalToolBar.style: Kirigami.ApplicationHeaderStyle.None
            pageStack.initialPage: Kirigami.Page {
                id: modulePage
                title: root.pageTitle; padding: 0
                globalToolBarStyle: Kirigami.ApplicationHeaderStyle.None
                header: Kirigami.AbstractApplicationHeader {
                    id: sectionHeader
                    objectName: "sectionHeader"
                    page: modulePage; pageRow: modulePane.pageStack
                    minimumHeight: root.paneHeaderHeight; preferredHeight: minimumHeight; maximumHeight: minimumHeight; height: minimumHeight
                    leftPadding: Kirigami.Units.largeSpacing*2; rightPadding: Kirigami.Units.largeSpacing
                    RowLayout {
                        width: parent.width
                        spacing: Kirigami.Units.mediumSpacing
                    ToolButton {
                        objectName: "assignmentBack"
                        visible: root.assignmentEditing
                        icon.name: "go-previous"
                        text: "Back"; display: AbstractButton.IconOnly
                        Accessible.name: "Back to button assignments"
                        onClicked: root.returnToAssignments()
                        ToolTip.visible: hovered; ToolTip.text: "Back to button assignments"
                    }
                    Kirigami.Heading { objectName: "sectionTitle"; text: root.assignmentEditing ? root.assignmentTitle : root.pageTitle; level: 2 }
                    Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
                    Label { text: "Device:" }
                    NativeComboBox { id: deviceSelector; objectName: "deviceSelect"; flat: true; Accessible.name: "Device"; model: backend.devices; textRole: "name"; currentIndex: backend.selectedDeviceIndex; Layout.preferredWidth: modulePane.width<800 ? 210 : 270; onActivated: { let target=currentIndex; root.requestNavigation(function() { backend.selectDevice(target); root.clearSelection(); root.shifted=false; }); } }
                    Label { text: "Profile:" }
                    NativeComboBox { id: profileSelector; objectName: "profileSelect"; flat: true; Accessible.name: "Profile"; model: backend.profiles; textRole: "name"; currentIndex: backend.selectedProfileIndex; Layout.preferredWidth: modulePane.width<800 ? 110 : 140; onActivated: { let target=currentIndex; root.requestNavigation(function() { backend.selectProfile(target); root.clearSelection(); }); } }
                    }
                }
            ColumnLayout {
                id: contentPane
                objectName: "contentPane"
                anchors.fill: parent; spacing: 0

            Kirigami.InlineMessage {
                objectName: "backendErrorMessage"
                Layout.fillWidth: true
                text: backend.error
                visible: backend.error!==""
                type: Kirigami.MessageType.Error
                showCloseButton: false
                actions: [
                    Kirigami.Action {
                        objectName: "dismissErrorAction"
                        text: "Dismiss"
                        icon.name: "dialog-close"
                        onTriggered: backend.clearError()
                    }
                ]
            }
            Kirigami.InlineMessage {
                objectName: "quickMacroValidation"
                Layout.fillWidth: true
                text: root.quickMacroError
                visible: root.quickMacroError!=="" && (!backend.connected || root.buttons.length===0)
                type: Kirigami.MessageType.Error
                actions: Kirigami.Action { text: "Cancel recording"; onTriggered: root.cancelQuickMacro() }
            }
            StackLayout {
                Layout.fillWidth: true; Layout.fillHeight: true
                currentIndex: root.assignmentEditing ? 4 : !backend.connected || !backend.devices.length ? 3 : (root.page===1 || root.page===2) ? 0 : root.page===4 ? 2 : 1
                ColumnLayout {
                    spacing: Kirigami.Units.largeSpacing
                    ColumnLayout {
                        objectName: "contentLayerHeader"
                        Layout.fillWidth: true
                        visible: root.page===1 && device.hasGShift===true
                        spacing: 0
                        ToolBar {
                            Layout.fillWidth: true
                            implicitHeight: contentItem.implicitHeight
                            padding: 0
                            contentItem: TabBar {
                                id: contentLayerTabs
                                objectName: "contentLayerTabs"
                                enabled: !backend.busy
                                Accessible.name: "Assignment layer"
                                currentIndex: root.shifted ? 1 : 0
                                onCurrentIndexChanged: {
                                    if (currentIndex>=0 && root.shifted!==(currentIndex===1)) {
                                        if(root.quickMacroIndex>=0) {
                                            root.quickMacroError="Finish or cancel the current recording before changing layers.";
                                            currentIndex=Qt.binding(function() { return root.shifted ? 1 : 0; });
                                        } else {
                                            root.shifted=currentIndex===1;
                                            root.clearSelection();
                                        }
                                    }
                                }
                                TabButton { baselineOffset: 0; objectName: "normalLayer"; text: "Normal" }
                                TabButton { baselineOffset: 0; objectName: "gshiftLayer"; text: "G-Shift" }
                            }
                        }
                        Kirigami.Separator { objectName: "contentLayerSeparator"; Layout.fillWidth: true }
                    }
                    RowLayout {
                        visible: root.page===2
                        Layout.fillWidth: true; Layout.margins: root.page===2 ? Kirigami.Units.largeSpacing*3 : Kirigami.Units.largeSpacing
                        Layout.leftMargin: root.page===2 ? Math.max(Kirigami.Units.largeSpacing*3, (contentPane.width-Kirigami.Units.gridUnit*56)/2) : Kirigami.Units.largeSpacing
                        Kirigami.Heading { text: root.page===2 ? "Lighting zones" : "Button assignments"; level: 2 }
                        Item { Layout.fillWidth: true }
                    }
                    RowLayout {
                        Layout.fillWidth: true; Layout.fillHeight: true; Layout.leftMargin: Kirigami.Units.largeSpacing; Layout.rightMargin: Kirigami.Units.largeSpacing
                        Layout.topMargin: root.page===1 ? Kirigami.Units.largeSpacing*2 : 0
                        Layout.maximumWidth: root.page===2 ? Kirigami.Units.gridUnit*56 : Number.POSITIVE_INFINITY
                        Layout.alignment: Qt.AlignHCenter
                        spacing: root.page===2 ? Kirigami.Units.largeSpacing*3 : Kirigami.Units.largeSpacing
                        ColumnLayout {
                            objectName: "diagramPane"
                            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumWidth: 300
                            Item {
                                id: diagramArea; objectName: "diagramArea"; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; activeFocusOnTab: true
                                Accessible.role: Accessible.Button
                                Accessible.name: root.page===2 ? "Mouse diagram. Arrow keys select a lighting zone; Enter edits it." : "Mouse diagram. Arrow keys select a button; Enter edits it."
                                Accessible.description: root.selectedTargetDescription
                                onActiveFocusChanged: if (!activeFocus) root.keyboardTargetActive=false
                                Keys.onRightPressed: root.nextTarget(1)
                                Keys.onLeftPressed: root.nextTarget(-1)
                                Keys.onDownPressed: root.nextTarget(1)
                                Keys.onUpPressed: root.nextTarget(-1)
                                Keys.onReturnPressed: if(root.hasSelection) root.chooseTarget(root.page===2?root.selectedLed:root.selectedButton)
                                Keys.onEnterPressed: if(root.hasSelection) root.chooseTarget(root.page===2?root.selectedLed:root.selectedButton)
                                property real scaleFactor: Math.min((width-30)/Math.max(1,root.bounds.width),(height-30)/Math.max(1,root.bounds.height),root.page===2 ? Kirigami.Units.gridUnit*29/Math.max(1,root.bounds.height) : Number.POSITIVE_INFINITY)
                                Image {
                                    id: mouseImage; objectName: "mouseDiagram"
                                    width: root.diagram.width*diagramArea.scaleFactor; height: root.diagram.height*diagramArea.scaleFactor
                                    x: (diagramArea.width-root.bounds.width*diagramArea.scaleFactor)/2-root.bounds.x*diagramArea.scaleFactor
                                    y: (diagramArea.height-root.bounds.height*diagramArea.scaleFactor)/2-root.bounds.y*diagramArea.scaleFactor
                                    source: root.diagram.source ? root.diagram.source+"&leaders=0&highlight="+root.diagramHighlight : ""
                                    sourceSize.width: Math.ceil(width*2); sourceSize.height: Math.ceil(height*2); fillMode: Image.Stretch; smooth: true; cache: false
                                    MouseArea {
                                        anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.ArrowCursor
                                        onPositionChanged: function(mouse) { root.keyboardTargetActive=false; let h=diagrams.hitTarget(device.svg||"",root.page===2?"leds":"buttons",mouse.x/diagramArea.scaleFactor,mouse.y/diagramArea.scaleFactor,root.diagramCount,root.shifted); root.hoverTarget=h.id||"" }
                                        onExited: { root.hoverTarget=""; root.keyboardTargetActive=false }
                                        onClicked: function(mouse) { let h=diagrams.hitTarget(device.svg||"",root.page===2?"leds":"buttons",mouse.x/diagramArea.scaleFactor,mouse.y/diagramArea.scaleFactor,root.diagramCount,root.shifted); if(h.index!==undefined && h.index>=0)root.selectDiagramTarget(h.index) }
                                    }

                                }
                            }
                            Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; text: root.page===2 ? "Select a lighting zone on the mouse or in the list to edit." : "Select a button on the mouse to find its assignment."; color: root.subtle }
                        }
                        Frame {
                            id: assignmentFrame; Layout.fillHeight: root.page!==2
                            Layout.alignment: Qt.AlignTop
                            Layout.preferredHeight: root.page===2 ? Math.min(parent.height, Kirigami.Units.gridUnit*3 + root.leds.length*Kirigami.Units.gridUnit*2.5) : -1
                            Layout.preferredWidth: root.page===2 ? Math.min(360,contentPane.width/2) : Math.min(540,Math.max(350,contentPane.width/2))
                            Layout.minimumWidth: Layout.preferredWidth
                            Layout.maximumWidth: Layout.preferredWidth
                            Kirigami.Theme.colorSet: Kirigami.Theme.View; Kirigami.Theme.inherit: false
                            ColumnLayout {
                                anchors.fill: parent; spacing: Kirigami.Units.smallSpacing
                                RowLayout {
                                    visible: root.page===2
                                    Label { text: root.page===2 ? root.leds.length + (root.leds.length===1 ? " lighting zone" : " lighting zones") : root.visibleAssignments.length+" assignments"; font.bold: true }
                                    Item { Layout.fillWidth: true }
                                    Label { visible: device.hasGShift===true && root.page===1; text: root.shifted ? "While G-Shift is held" : "Normal layer"; color: Kirigami.Theme.disabledTextColor }
                                }
                                ScrollView {
                                    id: assignmentsScroll; objectName: "assignmentsScroll"; Accessible.name: root.page===2 ? "Lighting zones" : "Button assignments"; Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                                    contentWidth: availableWidth
                                    GridLayout {
                                        id: assignmentGrid; objectName: "assignmentGrid"; width: assignmentsScroll.availableWidth
                                        columns: 1
                                        columnSpacing: Kirigami.Units.largeSpacing; rowSpacing: 0
                                        flow: GridLayout.TopToBottom
                                        rows: columns===2 ? Math.ceil(root.visibleAssignments.length/2) : root.visibleAssignments.length
                                        Repeater {
                                            id: assignmentRepeater
                                            model: root.visibleAssignments.length
                                            delegate: ItemDelegate {
                                                id: assignmentDelegate
                                                property alias quickMacroAction: quickMacroAction
                                                focusPolicy: Qt.StrongFocus
                                                activeFocusOnTab: true
                                                required property int index
                                                readonly property var modelData: root.visibleAssignments[index] || ({})
                                                Kirigami.Theme.useAlternateBackgroundColor: true
                                                Layout.fillWidth: true; Layout.minimumWidth: 0
                                                Layout.preferredWidth: (assignmentGrid.width-(assignmentGrid.columns-1)*assignmentGrid.columnSpacing)/assignmentGrid.columns
                                                Layout.maximumWidth: Layout.preferredWidth
                                                Layout.preferredHeight: root.page===2 ? Kirigami.Units.gridUnit*2.5 : Kirigami.Units.gridUnit*1.75 + (root.quickMacroIndex===modelData.index ? quickMacroStatusLabel.implicitHeight+quickMacroButtons.implicitHeight+Kirigami.Units.smallSpacing*2 : 0)
                                                topPadding: root.page===2 ? Kirigami.Units.mediumSpacing : Kirigami.Units.smallSpacing/2
                                                bottomPadding: topPadding
                                                objectName: root.page===2 ? "ledAssignment"+modelData.index : "buttonAssignment"+modelData.index
                                                Accessible.name: root.page===2 ? "Lighting zone "+(modelData.index+1) : "Button "+(modelData.physicalIndex+1)+", "+modelData.actionLabel
                                                highlighted: root.page===2 ? root.selectedLed===modelData.index : root.selectedButton===modelData.index
                                                onClicked: root.chooseTarget(modelData.index)
                                                Keys.onReturnPressed: root.chooseTarget(modelData.index)
                                                Keys.onEnterPressed: root.chooseTarget(modelData.index)
                                                onActiveFocusChanged: if(activeFocus) root.revealAssignment(modelData.index)
                                                onHoveredChanged: { if(hovered) root.keyboardTargetActive=false; root.hoverTarget=hovered ? (root.page===2 ? "led"+modelData.index : "button"+modelData.physicalIndex) : "" }
                                                contentItem: ColumnLayout {
                                                    spacing: Kirigami.Units.smallSpacing
                                                RowLayout {
                                                    Layout.fillWidth: true
                                                    Layout.preferredHeight: Kirigami.Units.gridUnit*1.5
                                                    Layout.minimumHeight: Layout.preferredHeight
                                                    Layout.maximumHeight: Layout.preferredHeight
                                                    spacing: Kirigami.Units.mediumSpacing
                                                    Label {
                                                        objectName: "assignmentLabel"+modelData.index
                                                        text: root.page===2 ? "Zone "+(modelData.index+1) : device.hasGShift && modelData.physicalIndex>=8 ? root.labelFor(modelData) : "Button "+(modelData.physicalIndex+1)
                                                        Layout.preferredWidth: Kirigami.Units.gridUnit*4.5
                                                        color: assignmentDelegate.highlighted ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
                                                    }
                                                    Label {
                                                        objectName: "assignmentValue"+modelData.index
                                                        Layout.fillWidth: true; Layout.minimumWidth: 0
                                                        text: root.page===2 ? ["Off","Solid","Cycle","Breathing"][modelData.mode||0] : root.compactMapping(modelData)
                                                        horizontalAlignment: Text.AlignRight; elide: Text.ElideMiddle
                                                        color: assignmentDelegate.highlighted ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
                                                    }
                                                    Rectangle { visible: root.page===2 && modelData.colorDepth>0; implicitWidth: Kirigami.Units.iconSizes.small; implicitHeight: implicitWidth; color: modelData.color || "transparent"; border.color: Kirigami.Theme.disabledTextColor }
                                                    ToolButton {
                                                        id: quickMacroAction
                                                        objectName: "buttonQuickMacro"+modelData.index
                                                        visible: root.page===1
                                                        enabled: (modelData.actionTypes || []).indexOf("macro")>=0
                                                        icon.name: "input-keyboard"; display: AbstractButton.IconOnly
                                                        icon.width: Kirigami.Units.iconSizes.small; icon.height: Kirigami.Units.iconSizes.small
                                                        Layout.preferredWidth: Kirigami.Units.gridUnit*1.5
                                                        Layout.preferredHeight: Kirigami.Units.gridUnit*1.5
                                                        text: "Record shortcut for button "+(modelData.physicalIndex+1)
                                                        Accessible.name: text
                                                        focusPolicy: Qt.StrongFocus; activeFocusOnTab: true
                                                        onClicked: root.startQuickMacro(modelData.index)
                                                        Keys.onReturnPressed: clicked()
                                                        Keys.onEnterPressed: clicked()
                                                        onActiveFocusChanged: if(activeFocus) root.revealAssignment(modelData.index)
                                                        ToolTip.visible: hovered; ToolTip.text: text
                                                    }
                                                    ToolButton {
                                                        objectName: root.page===2 ? "ledEdit"+modelData.index : "buttonEdit"+modelData.index
                                                        icon.name: root.page===2 ? "document-edit" : "go-next"; display: AbstractButton.IconOnly
                                                        icon.width: Kirigami.Units.iconSizes.small; icon.height: Kirigami.Units.iconSizes.small
                                                        Layout.preferredWidth: Kirigami.Units.gridUnit*1.5
                                                        Layout.preferredHeight: Kirigami.Units.gridUnit*1.5
                                                        Layout.maximumHeight: Layout.preferredHeight
                                                        text: root.page===2 ? "Edit lighting zone "+(modelData.index+1) : "Edit button "+(modelData.physicalIndex+1)+" assignment"
                                                        Accessible.name: text
                                                        focusPolicy: Qt.StrongFocus; activeFocusOnTab: true
                                                        onClicked: root.chooseTarget(modelData.index)
                                                        Keys.onReturnPressed: root.chooseTarget(modelData.index)
                                                        Keys.onEnterPressed: root.chooseTarget(modelData.index)
                                                        onActiveFocusChanged: if(activeFocus) root.revealAssignment(modelData.index)
                                                        ToolTip.visible: hovered; ToolTip.text: text
                                                    }
                                                }
                                                ColumnLayout {
                                                    objectName: "quickMacroPanel"+modelData.index
                                                    visible: root.page===1 && root.quickMacroIndex===modelData.index
                                                    Layout.fillWidth: true
                                                    Label {
                                                        id: quickMacroStatusLabel
                                                        objectName: "quickMacroStatus"+modelData.index
                                                        text: root.quickMacroError || root.quickMacroPreview
                                                        color: root.quickMacroError ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
                                                        wrapMode: Text.WordWrap; Layout.fillWidth: true
                                                    }
                                                    RowLayout {
                                                        id: quickMacroButtons
                                                        Button {
                                                            objectName: "quickMacroStop"+modelData.index
                                                            text: macroRecorder.active ? "Stop recording" : macroRecorder.events.length && root.quickMacroError==="" ? "Use shortcut" : "Record again"
                                                            onClicked: macroRecorder.active || (macroRecorder.events.length && root.quickMacroError==="") ? root.finishQuickMacro() : root.startQuickMacro(modelData.index)
                                                        }
                                                        Button { objectName: "quickMacroCancel"+modelData.index; text: "Cancel"; onClicked: root.cancelQuickMacro() }
                                                    }
                                                }
                                                }
                                                ToolTip.visible: hovered; ToolTip.text: root.page===2 ? "Edit lighting zone" : modelData.actionLabel
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Item { height: Kirigami.Units.smallSpacing }
                }
                ScrollView {
                    id: settingsScroll
                    Connections { target: root; function onActiveFocusItemChanged() { root.revealSettingsFocus(settingsScroll) } }
                    objectName: "settingsScroll"
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    contentWidth: availableWidth
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ColumnLayout {
                        id: settingsContent
                        width: Math.min(Kirigami.Units.gridUnit*42, settingsScroll.availableWidth-Kirigami.Units.largeSpacing*6)
                        x: (settingsScroll.availableWidth-width)/2
                        spacing: Kirigami.Units.largeSpacing*2
                        Item { Layout.preferredHeight: Kirigami.Units.largeSpacing }
                        Kirigami.Heading { text: root.page===0 ? "DPI stages" : "Device settings"; level: 2 }
                        Label {
                            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: root.subtle
                            text: root.page===0 ? "Adjust pointer speed and polling rate for " + (profile.name || "this profile") + "." : "Device-specific settings for " + (profile.name || "this profile") + "."
                        }
                        ColumnLayout {
                            visible: root.page===0; Layout.fillWidth: true
                            spacing: Kirigami.Units.largeSpacing*2
                            GridLayout {
                                id: stagesGrid
                                Layout.fillWidth: true
                                columns: width>=Kirigami.Units.gridUnit*34 ? 2 : 1
                                columnSpacing: Kirigami.Units.largeSpacing*2
                                rowSpacing: Kirigami.Units.largeSpacing*2
                                Repeater {
                                    model: resolutions
                                    delegate: GroupBox {
                                        required property var modelData
                                        objectName: "resolutionStage"+modelData.index
                                        title: "Stage " + (modelData.index+1)
                                        Layout.fillWidth: true; Layout.minimumWidth: 0
                                        Layout.preferredWidth: (stagesGrid.width-stagesGrid.columnSpacing)/stagesGrid.columns
                                        ColumnLayout {
                                            anchors.fill: parent
                                            spacing: Kirigami.Units.largeSpacing
                                            Kirigami.FormLayout {
                                                Layout.fillWidth: true
                                                NativeComboBox {
                                                    id: dpiX; objectName: "dpiX"+modelData.index
                                                    Kirigami.FormData.label: modelData.separateXY ? "X axis:" : "Sensitivity:"
                                                    Accessible.name: "Stage " + (modelData.index+1) + (modelData.separateXY ? " X axis DPI" : " DPI")
                                                    Layout.preferredWidth: Kirigami.Units.gridUnit*9
                                                    model: modelData.values || []; currentIndex: model.indexOf(modelData.x)
                                                    displayText: currentText + " DPI"
                                                    onActivated: backend.setDpi(modelData.index,Number(currentText),modelData.separateXY ? Number(dpiY.currentText) : Number(currentText))
                                                }
                                                NativeComboBox {
                                                    id: dpiY; objectName: "dpiY"+modelData.index
                                                    Kirigami.FormData.label: "Y axis:"
                                                    Accessible.name: "Stage " + (modelData.index+1) + " Y axis DPI"
                                                    Layout.preferredWidth: Kirigami.Units.gridUnit*9
                                                    visible: modelData.separateXY === true
                                                    model: modelData.values || []; currentIndex: model.indexOf(modelData.y)
                                                    displayText: currentText + " DPI"
                                                    onActivated: backend.setDpi(modelData.index,Number(dpiX.currentText),Number(currentText))
                                                }
                                            }
                                            RowLayout {
                                                Layout.alignment: Qt.AlignHCenter
                                                spacing: Kirigami.Units.largeSpacing
                                                CheckBox {
                                                    text: "Enabled"; objectName: "resolutionEnabled"+modelData.index
                                                    Accessible.name: "Stage "+(modelData.index+1)+" enabled"
                                                    checked: modelData.enabled !== false; enabled: modelData.canDisable === true
                                                    onClicked: backend.setResolutionEnabled(modelData.index,checked)
                                                    ToolTip.visible: hovered; ToolTip.text: enabled ? "Include this stage when cycling sensitivity." : "This device keeps every DPI stage enabled."
                                                }
                                                RadioButton { text: "Active"; objectName: "resolutionActive"+modelData.index; Accessible.name: "Stage "+(modelData.index+1)+" active"; autoExclusive: false; checked: modelData.active; onClicked: backend.setResolutionActive(modelData.index) }
                                                RadioButton { text: "Default"; objectName: "resolutionDefault"+modelData.index; Accessible.name: "Stage "+(modelData.index+1)+" default"; autoExclusive: false; checked: modelData.default; onClicked: backend.setResolutionDefault(modelData.index) }
                                            }
                                        }
                                    }
                                }
                            }
                            Kirigami.FormLayout {
                                NativeComboBox {
                                    objectName: "reportRate"
                                    Kirigami.FormData.label: "Polling rate:"
                                    Accessible.name: "Polling rate"
                                    Layout.preferredWidth: Kirigami.Units.gridUnit*12
                                    model: profile.reportRates || []; enabled: count > 0
                                    currentIndex: model.indexOf(profile.reportRate)
                                    displayText: count ? currentText + " Hz" : "Not supported"
                                    onActivated: backend.setReportRate(Number(currentText))
                                }
                            }
                            Label {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap; color: root.subtle
                                text: "Active is the current DPI stage. Default is the stage used by the Default DPI button action."
                            }
                            Button { text: "Advanced settings"; icon.name: "settings-configure"; objectName: "advancedSettingsLink"; onClicked: root.page=3 }
                        }
                        ColumnLayout {
                            visible: root.page===3; Layout.fillWidth: true
                            spacing: Kirigami.Units.largeSpacing*2
                            Kirigami.FormLayout {
                                RowLayout {
                                    Kirigami.FormData.label: "Angle snapping:"
                                    CheckBox {
                                        text: "Enabled"; objectName: "angleSnapping"; Accessible.name: "Enable angle snapping"
                                        enabled: root.profile.angleSnapping !== undefined && root.profile.angleSnapping !== -1
                                        checked: root.profile.angleSnapping === 1; onClicked: backend.setAngleSnapping(checked)
                                    }
                                    Label { visible: root.profile.angleSnapping === undefined || root.profile.angleSnapping === -1; text: "Not supported"; color: root.subtle }
                                }
                                NativeComboBox {
                                    objectName: "debounce"
                                    Kirigami.FormData.label: "Debounce time:"
                                    Accessible.name: "Debounce time"
                                    Layout.preferredWidth: Kirigami.Units.gridUnit*14
                                    model: root.profile.debounces || []; enabled: count > 0
                                    currentIndex: model.indexOf(root.profile.debounce)
                                    displayText: count ? currentText + " ms" : "Not supported"
                                    onActivated: backend.setDebounce(Number(currentText))
                                }
                                NativeComboBox {
                                    objectName: "advancedReportRate"
                                    Kirigami.FormData.label: "Polling rate:"
                                    Accessible.name: "Polling rate"
                                    Layout.preferredWidth: Kirigami.Units.gridUnit*14
                                    model: root.profile.reportRates || []; enabled: count > 0
                                    currentIndex: model.indexOf(root.profile.reportRate)
                                    displayText: count ? currentText + " Hz" : "Not supported"
                                    onActivated: backend.setReportRate(Number(currentText))
                                }
                            }
                            Label {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap; color: root.subtle
                                text: "Unavailable settings are not supported by this device’s ratbagd driver."
                            }
                        }
                        Item { Layout.preferredHeight: Kirigami.Units.largeSpacing*2 }
                    }
                }
                ScrollView {
                    id: profilesScroll
                    Connections { target: root; function onActiveFocusItemChanged() { root.revealSettingsFocus(profilesScroll) } }
                    objectName: "profilesScroll"
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    contentWidth: availableWidth
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ColumnLayout {
                        width: Math.min(Kirigami.Units.gridUnit*42, profilesScroll.availableWidth-Kirigami.Units.largeSpacing*6)
                        x: (profilesScroll.availableWidth-width)/2
                        spacing: Kirigami.Units.largeSpacing*2
                        Item { Layout.preferredHeight: Kirigami.Units.largeSpacing }
                        Kirigami.Heading { text: "On-device profiles"; level: 2 }
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: "Select a profile from the toolbar to edit its settings."; color: root.subtle }
                        Kirigami.FormLayout {
                            TextField {
                                text: profile.name||""; objectName: "profileName"
                                Kirigami.FormData.label: "Name:"
                                Accessible.name: "Profile name"
                                Layout.preferredWidth: Kirigami.Units.gridUnit*18
                                enabled: profile.canRename===true
                                onEditingFinished: if(text!==profile.name) backend.setProfileName(text)
                            }
                            Label { visible: profile.canRename!==true; text: "Renaming is not supported by this device."; color: root.subtle }
                            CheckBox {
                                text: "Enabled"; objectName: "profileEnabled"; Accessible.name: "Enable selected profile"
                                Kirigami.FormData.label: "Profile:"
                                checked: profile.enabled!==false; enabled: profile.canDisable===true
                                onClicked: backend.setProfileEnabled(checked)
                            }
                            Label { visible: profile.canDisable!==true; text: "This device keeps all profiles enabled."; color: root.subtle }
                            RowLayout {
                                Kirigami.FormData.label: "Status:"
                                Label { text: profile.active ? "Active profile" : "Inactive profile" }
                                Button { text: "Make active"; objectName: "activateProfile"; visible: !profile.active; enabled: !profile.active; onClicked: backend.setProfileActive() }
                            }
                        }
                        Item { Layout.preferredHeight: Kirigami.Units.largeSpacing*2 }
                    }
                }
                Kirigami.PlaceholderMessage { text: "No connected device"; explanation: "Connect a supported mouse and make sure ratbagd is running."; helpfulAction: Kirigami.Action { text: "Refresh"; onTriggered: backend.refresh() } }
                AssignmentPage {
                    id: assignmentPage; objectName: "assignmentPage"; backendObject: backend
                    onApplied: function(success) {
                        if(root.applyThenNavigate && success) root.completeAssignmentNavigation();
                        else root.applyThenNavigate=false;
                    }
                }
            }
            ToolBar {
                objectName: "pendingChangesBar"
                Layout.fillWidth: true
                position: ToolBar.Footer
                padding: Kirigami.Units.smallSpacing
                contentItem: RowLayout {
                    spacing: Kirigami.Units.mediumSpacing
                    Button { objectName: "helpButton"; action: contextHelpAction; visible:root.contextHelpAvailable }
                    Button { text: root.page===1 && !root.assignmentEditing ? "Revert" : "Reset"; icon.name: "edit-undo"; objectName: "resetButton"; enabled: !backend.busy && (root.assignmentEditing ? assignmentPage.edited && assignmentPage.contextValid : root.page===1 ? backend.profileMappingsDirty || root.quickMacroIndex>=0 : root.settingsPageDirty); onClicked: root.assignmentEditing ? assignmentPage.resetDraft() : root.page===1 ? root.revertProfileAssignments() : backend.resetPage(root.settingsPageContext) }
                    Button {
                        objectName: "defaultsButton"
                        visible: root.page===1
                        text: "Defaults"
                        icon.name: "document-revert"
                        enabled: root.defaultsAvailable && root.defaultsDiffer
                        Accessible.description: "Automatic factory-default restoration is not safely supported for this device. No settings will be changed."
                    }
                    Label {
                        objectName: "defaultsUnavailable"
                        visible: false
                        text: "Automatic restore unavailable"
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        color: root.subtle
                    }
                    Item { Layout.fillWidth: true }
                    Label {
                        objectName: "pendingChangesStatus"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.maximumWidth: implicitWidth
                        elide: Text.ElideRight
                        visible: root.assignmentEditing ? assignmentPage.edited || assignmentPage.applying : root.page===1 ? backend.profileMappingsDirty || backend.busy : root.settingsPageDirty || backend.busy
                        text: backend.busy ? "Applying changes…" : root.page===1 ? "Unsaved assignment changes" : "Unsaved changes"
                        color: root.foreground
                    }
                    Button { text: "Apply"; icon.name: "dialog-ok-apply"; objectName: "applyButton"; Accessible.description: root.assignmentEditing ? "Apply only this assignment." : root.page===1 ? "Apply pending button assignments in the selected profile. Other settings are unchanged." : "Apply only pending "+root.pageTitle.toLowerCase()+" settings."; ToolTip.visible: hovered; ToolTip.text: Accessible.description; highlighted: root.assignmentEditing ? assignmentPage.edited : root.page===1 ? backend.profileMappingsDirty : root.settingsPageDirty; enabled: root.assignmentEditing ? assignmentPage.canApply : root.page===1 ? backend.profileMappingsDirty && root.quickMacroIndex<0 && !backend.busy && backend.connected : root.settingsPageDirty && !backend.busy && backend.connected; onClicked: root.assignmentEditing ? assignmentPage.applyDraft() : root.page===1 ? root.applyProfileAssignments() : backend.applyPage(root.settingsPageContext) }
                }
            }
            }
            }
        }
    }
    }
    Dialog {
        id: assignmentNavigationDialog
        objectName: "assignmentNavigationDialog"
        title: "Unsaved assignment changes"
        modal: true; anchors.centerIn: parent
        width: Math.min(Kirigami.Units.gridUnit*30,parent.width-Kirigami.Units.largeSpacing*2)
        closePolicy: Popup.NoAutoClose
        contentItem: ColumnLayout {
            Label {
                Layout.fillWidth: true
                Layout.preferredWidth: assignmentNavigationDialog.width-assignmentNavigationDialog.leftPadding-assignmentNavigationDialog.rightPadding
                text: "Apply this assignment before leaving, discard its changes, or keep editing? Other pending settings will not be changed."
                wrapMode: Text.WordWrap
            }
            Kirigami.InlineMessage {
                objectName: "assignmentNavigationError"
                Layout.fillWidth: true
                text: assignmentPage.validation
                visible: text!==""
                type: Kirigami.MessageType.Error
            }
        }
        footer: DialogButtonBox {
            Button { objectName: "assignmentKeepEditing"; text: "Keep editing"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole; onClicked: { root.pendingAssignmentNavigation=null; root.applyThenNavigate=false; assignmentNavigationDialog.close(); assignmentPage.focusFirst(); } }
            Button { objectName: "assignmentDiscardChanges"; text: "Discard changes"; enabled: !backend.busy; DialogButtonBox.buttonRole: DialogButtonBox.DestructiveRole; onClicked: if(assignmentPage.discardDraft()) root.completeAssignmentNavigation() }
            Button { objectName: "assignmentApplyContinue"; text: "Apply and continue"; enabled: assignmentPage.canApply; DialogButtonBox.buttonRole: DialogButtonBox.ApplyRole; onClicked: { root.applyThenNavigate=true; if(!assignmentPage.applyDraft()) root.applyThenNavigate=false; } }
        }
    }
    Dialog {
        id: closeDialog; objectName: "closeDialog"; title: "Unsaved changes"; modal: true; anchors.centerIn: parent; width: 400
        contentItem: ColumnLayout {
            Label { text: "Close Piper and discard the changes you have not applied?"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            RowLayout { Item { Layout.fillWidth: true } Button { text: "Keep editing"; objectName: "keepEditingButton"; onClicked: closeDialog.close() } Button { text: "Discard and close"; objectName: "discardCloseButton"; enabled: !backend.busy; onClicked: { root.discardOnClose=true; root.close() } } }
        }
    }

    LedDialog { id: ledDialog; backendObject: backend }
}
