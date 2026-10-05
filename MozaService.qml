import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: root
  property var rows: ({})
  property var groups: ({})
  property var pages: []
  property var panels: []
  property var rev: ({})
  property var config: ({start: 80, full: 97, leds: 10, enabled: true})
  property string error: ""
  property string message: ""
  property bool ready: false
  property bool dialog: false
  property bool destroying: false
  property bool demo: false
  property string current: "Rev lights"
  property bool panelOpen: false
  property var instances: []
  property string layoutKey: ""
  property string panelsKey: ""

  function send(request) { if (backend.running) backend.write(JSON.stringify(request) + "\n") }
  function selectPage(name, opened) {
    current = name; panelOpen = opened
    send({op: "focus", name: name, opened: opened})
  }
  function act(id, action, value, index) {
    send({op: "act", id: id, action: action, value: value, index: index || 0})
  }
  function setRev(key, value) {
    var next = Object.assign({}, config); next[key] = value
    send({op: "rev", config: next})
  }
  function ingest(line) {
    if (line.length > 1048576) return
    var data
    try { data = JSON.parse(line) } catch (e) { return }
    if (!data || !data.panels) return
    ready = true
    rev = data.rev || {}; config = data.config || config
    error = data.error || rev.error || ""; message = data.message || ""
    dialog = !!data.dialog; demo = !!data.demo
    var rowState = {}, groupState = {}
    function rowLayout(row) {
      rowState[row.id] = row
      return {id: row.id, children: (row.rows || []).map(rowLayout)}
    }
    var layout = (data.pages || []).map(function(page) {
      return {title: page.title, groups: page.groups.map(function(group) {
        groupState[group.id] = group
        return {id: group.id, rows: group.rows.map(rowLayout)}
      })}
    })
    rows = rowState; groups = groupState
    var key = JSON.stringify(layout)
    if (key !== layoutKey) { layoutKey = key; pages = layout }
    var pkey = JSON.stringify(data.panels)
    if (pkey !== panelsKey) { panelsKey = pkey; panels = data.panels }
  }
  function show(name) {
    selectPage(name || current, true)
    for (var i = 0; i < instances.length; ++i) {
      var item = instances[i]
      if (item && item.bar && item.bar.shell) { item.bar.shell.summon("crmne.moza", "{}"); return }
    }
  }
  Process {
    id: backend
    command: ["/usr/bin/python3", "-B", "-I", Qt.resolvedUrl("backend/bridge.py").toString().replace(/^file:\/\//, "")]
    running: true
    stdinEnabled: true
    stdout: SplitParser { onRead: line => root.ingest(line) }
    onStarted: root.selectPage(root.current, root.panelOpen)
    onExited: function(code, status) {
      root.ready = false
      if (!root.destroying) root.error = "MOZA backend stopped. Check dependencies and re-enable the plugin."
    }
  }
  Component.onDestruction: {
    destroying = true
    if (backend.running) { send({op: "quit"}); backend.running = false }
  }
  IpcHandler {
    target: "crmne.moza"
    function status(): string { return JSON.stringify({ready: root.ready, rev: root.rev, config: root.config, error: root.error}) }
    function show(page: string): void { root.show(page) }
    function hide(): void { root.instances.forEach(item => { if (item) item.close() }) }
    function configure(start: int, full: int): void { root.send({op: "rev", config: Object.assign({}, root.config, {start: start, full: full})}) }
  }
}
