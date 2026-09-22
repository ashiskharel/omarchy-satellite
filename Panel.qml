import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "ashis.satellite"
  ipcTarget: "ashis.satellite"
  manageIpc: false

  property var anchorItem: null
  property bool openedFromHotkey: false
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  property var report: ({})
  property string label: "—"
  property string status: ""
  property bool refreshing: false
  property int selectedNorad: 25544

  readonly property var satellites: report && report.satellites ? report.satellites : []
  readonly property var selected: {
    for (var i = 0; i < satellites.length; i++) {
      if (satellites[i].norad === selectedNorad) return satellites[i]
    }
    return satellites.length ? satellites[0] : null
  }
  readonly property color ink: bar ? bar.foreground : Color.foreground
  readonly property string face: bar ? bar.fontFamily : Style.font.family

  function scriptPath() {
    var url = String(Qt.resolvedUrl("track.py"))
    if (url.indexOf("file://") === 0) url = url.slice(7)
    return decodeURIComponent(url)
  }

  function open() {
    openedFromHotkey = false
    setCenterHoverRevealSuppressed(false)
    root.controller.show()
    refresh(false)
  }

  function openFromHotkey() {
    openedFromHotkey = true
    root.controller.show()
    refresh(false)
    Qt.callLater(function() {
      if (root.opened) setCenterHoverRevealSuppressed(true)
    })
  }

  function close() {
    setCenterHoverRevealSuppressed(false)
    root.controller.hide()
  }

  function toggle() {
    if (root.opened) root.close()
    else root.openFromHotkey()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function setCenterHoverRevealSuppressed(value) {
    if (root.bar && typeof root.bar.setCenterHoverRevealSuppressed === "function")
      root.bar.setCenterHoverRevealSuppressed(value)
    else if (root.bar && "centerHoverRevealSuppressed" in root.bar)
      root.bar.centerHoverRevealSuppressed = value
  }

  function refresh(force) {
    if (trackProc.running) return
    refreshing = true
    status = force ? "Pinging CelesTrak…" : ""
    trackProc.command = force ? ["python3", scriptPath(), "--refresh"] : ["python3", scriptPath()]
    trackProc.running = true
  }

  function applyReport(raw) {
    var parsed
    try {
      parsed = JSON.parse(raw)
    } catch (e) {
      status = "Tracker returned something unreadable"
      return
    }
    report = parsed
    label = parsed.label || "—"
    if (parsed.featured) selectedNorad = parsed.featured
    status = parsed.error ? parsed.error : ""
    sky.requestPaint()
  }

  Component.onCompleted: refresh(false)

  Timer {
    interval: 60000
    running: true
    repeat: true
    onTriggered: root.refresh(false)
  }

  Process {
    id: trackProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyReport(text || "")
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var err = String(text || "").trim()
        if (err !== "" && root.status === "") root.status = err
      }
    }
    onExited: function(code) {
      root.refreshing = false
      if (code !== 0 && root.status === "") root.status = "Tracker stopped"
    }
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.openFromHotkey() }
    function close(): void { root.close() }
    function show(): void { root.openFromHotkey() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): void { root.refresh(true) }
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: column
          width: parent.width
          spacing: Style.space(12)
          topPadding: Style.space(4)

          Row {
            width: parent.width - Style.space(8)
            x: Style.space(4)
            spacing: Style.space(8)

            Column {
              width: parent.width - ping.width - Style.space(8)
              spacing: 2

              Text {
                text: root.selected ? root.selected.name : "Satellite"
                color: root.ink
                font.family: root.face
                font.pixelSize: Style.font.heading
              }

              Text {
                text: {
                  var loc = root.report && root.report.location
                  if (!loc) return root.refreshing ? "Finding you…" : "No location yet"
                  var where = loc.name || "Here"
                  var via = loc.source === "weather" ? "from weather" : "from this network"
                  return where + " · " + via
                }
                color: root.ink
                opacity: 0.6
                font.family: root.face
                font.pixelSize: Style.font.bodySmall
              }
            }

            Text {
              id: ping
              text: root.refreshing ? "Pinging…" : "Ping"
              color: root.ink
              font.family: root.face
              font.pixelSize: Style.font.body
              font.underline: true
              anchors.verticalCenter: parent.verticalCenter

              MouseArea {
                anchors.fill: parent
                enabled: !root.refreshing
                cursorShape: Qt.PointingHandCursor
                onClicked: root.refresh(true)
              }
            }
          }

          Row {
            width: parent.width
            spacing: Style.space(16)
            leftPadding: Style.space(4)

            Column {
              spacing: 2
              Text {
                text: root.selected && root.selected.elevation !== undefined ? Math.round(root.selected.elevation) + "°" : "—"
                color: root.ink
                font.family: root.face
                font.pixelSize: Style.font.displayLarge
              }
              Text {
                text: "elevation"
                color: root.ink
                opacity: 0.55
                font.family: root.face
                font.pixelSize: Style.font.caption
              }
            }

            Column {
              spacing: 2
              anchors.bottom: parent.bottom
              anchors.bottomMargin: Style.space(4)
              Text {
                text: root.selected && root.selected.azimuth !== undefined
                      ? Math.round(root.selected.azimuth) + "° " + root.selected.compass
                      : "—"
                color: root.ink
                font.family: root.face
                font.pixelSize: Style.font.title
              }
              Text {
                text: {
                  if (!root.selected || root.selected.elevation === undefined) return "azimuth"
                  var way = root.selected.rising ? "rising" : "setting"
                  var range = root.selected.range_km !== undefined ? " · " + root.selected.range_km + " km" : ""
                  return "azimuth · " + way + range
                }
                color: root.ink
                opacity: 0.55
                font.family: root.face
                font.pixelSize: Style.font.caption
              }
            }
          }

          Canvas {
            id: sky
            x: (parent.width - width) / 2
            width: Style.space(168)
            height: width
            onPaint: {
              var ctx = getContext("2d")
              ctx.reset()
              var c = width / 2
              var radius = c - 14
              ctx.strokeStyle = root.ink
              ctx.fillStyle = root.ink
              ctx.globalAlpha = 0.28
              ctx.lineWidth = 1
              ctx.beginPath()
              ctx.arc(c, c, radius, 0, Math.PI * 2)
              ctx.stroke()
              ctx.beginPath()
              ctx.arc(c, c, radius * 0.5, 0, Math.PI * 2)
              ctx.stroke()
              ctx.beginPath()
              ctx.moveTo(c, c - radius)
              ctx.lineTo(c, c + radius)
              ctx.moveTo(c - radius, c)
              ctx.lineTo(c + radius, c)
              ctx.stroke()
              ctx.globalAlpha = 0.7
              ctx.font = Style.font.caption + "px " + root.face
              ctx.fillText("N", c - 4, 12)
              ctx.fillText("E", width - 12, c + 4)
              ctx.fillText("S", c - 3, height - 4)
              ctx.fillText("W", 2, c + 4)

              for (var i = 0; i < root.satellites.length; i++) {
                var sat = root.satellites[i]
                if (sat.elevation === undefined || sat.elevation <= 0) continue
                var rr = (90 - Math.min(90, sat.elevation)) / 90 * radius
                var rad = sat.azimuth * Math.PI / 180
                var x = c + rr * Math.sin(rad)
                var y = c - rr * Math.cos(rad)
                var chosen = root.selected && sat.norad === root.selected.norad
                ctx.globalAlpha = chosen ? 1 : 0.45
                ctx.beginPath()
                ctx.arc(x, y, chosen ? 5 : 3.5, 0, Math.PI * 2)
                ctx.fill()
              }
            }
          }

          Column {
            width: parent.width - Style.space(8)
            x: Style.space(4)
            spacing: Style.space(6)

            Repeater {
              model: root.satellites

              delegate: Rectangle {
                required property var modelData
                width: parent.width
                height: Style.space(36)
                radius: Style.space(6)
                color: "transparent"

                Rectangle {
                  anchors.fill: parent
                  radius: parent.radius
                  color: root.ink
                  opacity: root.selected && modelData.norad === root.selected.norad ? 0.12 : 0
                }

                Row {
                  anchors.fill: parent
                  anchors.leftMargin: Style.space(8)
                  anchors.rightMargin: Style.space(8)
                  spacing: Style.space(8)

                  Text {
                    text: modelData.short || modelData.name
                    color: root.ink
                    font.family: root.face
                    font.pixelSize: Style.font.body
                    width: Style.space(72)
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  Text {
                    text: modelData.elevation !== undefined ? Math.round(modelData.elevation) + "° el" : (modelData.error || "—")
                    color: root.ink
                    opacity: 0.75
                    font.family: root.face
                    font.pixelSize: Style.font.bodySmall
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  Item { width: Style.space(8); height: 1 }

                  Text {
                    text: {
                      if (modelData.overhead) return "overhead"
                      if (modelData.next) return "in " + modelData.next.in_min + "m · max " + modelData.next.max_el + "°"
                      return "no pass soon"
                    }
                    color: root.ink
                    opacity: 0.75
                    font.family: root.face
                    font.pixelSize: Style.font.bodySmall
                    anchors.verticalCenter: parent.verticalCenter
                    horizontalAlignment: Text.AlignRight
                    width: parent.width - Style.space(160)
                  }
                }

                MouseArea {
                  anchors.fill: parent
                  onClicked: {
                    root.selectedNorad = modelData.norad
                    sky.requestPaint()
                  }
                }
              }
            }
          }

          Text {
            x: Style.space(4)
            width: parent.width - Style.space(8)
            wrapMode: Text.WordWrap
            color: root.ink
            opacity: 0.5
            font.family: root.face
            font.pixelSize: Style.font.caption
            text: {
              if (root.status !== "") return root.status
              var age = root.report ? root.report.tle_age_min : undefined
              if (age === undefined) return ""
              var when = root.report.updated || ""
              return "Orbits from CelesTrak · " + age + " min old · updated " + when
            }
          }
        }
      }
    }
  }

  onSelectedChanged: sky.requestPaint()
}
